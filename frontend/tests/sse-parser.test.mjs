import assert from "node:assert/strict";
import { test } from "node:test";
import { createSseParser, parseSseText, postEventStream, readEventStream, SseHttpError } from "../src/services/streaming/sse.ts";

const pick = (events) => events.map(({ event, data }) => ({ event, data }));

function feed(chunks) {
  const parser = createSseParser();
  const events = [];
  for (const chunk of chunks) events.push(...parser.push(chunk));
  events.push(...parser.end());
  return pick(events);
}

test("frames split at every possible chunk boundary parse identically", () => {
  const body = 'event: stage\ndata: {"id":"retrieve","status":"running"}\n\nevent: token\ndata: {"delta":"Hi"}\n\n';
  const whole = feed([body]);
  assert.deepEqual(whole, [
    { event: "stage", data: '{"id":"retrieve","status":"running"}' },
    { event: "token", data: '{"delta":"Hi"}' },
  ]);
  for (let cut = 1; cut < body.length; cut += 1) {
    assert.deepEqual(feed([body.slice(0, cut), body.slice(cut)]), whole, `cut at ${cut}`);
  }
  assert.deepEqual(feed([...body]), whole, "one character per chunk");
});

test("CRLF, lone CR and a CRLF split across chunks are single line ends", () => {
  assert.deepEqual(feed(["event: token\r\ndata: a\r\n\r\n"]), [{ event: "token", data: "a" }]);
  assert.deepEqual(feed(["event: token\rdata: b\r\r"]), [{ event: "token", data: "b" }]);
  // "\r" ends one chunk and "\n" starts the next: no phantom blank line, so
  // the event name must survive until the real blank line.
  assert.deepEqual(feed(["event: token\r", "\ndata: c\r", "\n\r", "\n"]), [{ event: "token", data: "c" }]);
});

test("multi-line data joins with newlines and a single leading space is stripped", () => {
  assert.deepEqual(feed(["data: line one\ndata:line two\ndata:  indented\n\n"]), [
    { event: "message", data: "line one\nline two\n indented" },
  ]);
  assert.deepEqual(feed(["data\n\n"]), [{ event: "message", data: "" }], "a bare data field is an empty line");
});

test("comments, unknown fields and frames without data are ignored", () => {
  assert.deepEqual(feed([": ping\n\n: another\nfoo: bar\n\nevent: stage\n\n", 'event: token\ndata: {"delta":"x"}\n\n']), [
    { event: "token", data: '{"delta":"x"}' },
  ]);
});

test("id and retry fields are kept; a BOM at the start is dropped", () => {
  const [event] = parseSseText("﻿id: 7\nretry: 1500\nevent: token\ndata: z\n\n");
  assert.deepEqual(event, { event: "token", data: "z", id: "7", retry: 1500 });
});

test("a final frame without its trailing blank line is still delivered", () => {
  assert.deepEqual(feed(['event: message.completed\ndata: {"message":{"id":1}}']), [
    { event: "message.completed", data: '{"message":{"id":1}}' },
  ]);
  assert.deepEqual(feed(["event: error\ndata: {}\r"]), [{ event: "error", data: "{}" }]);
  assert.deepEqual(feed(["data: done\n"]), [{ event: "message", data: "done" }]);
});

function streamOf(chunks) {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

test("multi-byte characters split across byte chunks are decoded intact", async () => {
  const bytes = new TextEncoder().encode('event: token\ndata: {"delta":"naïve 𝐱 ✓"}\n\n');
  const chunks = [];
  for (let i = 0; i < bytes.length; i += 3) chunks.push(bytes.slice(i, i + 3));
  const events = [];
  await readEventStream(streamOf(chunks), (event) => events.push(event));
  assert.deepEqual(pick(events), [{ event: "token", data: '{"delta":"naïve 𝐱 ✓"}' }]);
});

test("postEventStream sends the bearer header and reads the stream", async () => {
  let seen;
  const fetchImpl = async (url, init) => {
    seen = { url, init };
    return new Response(streamOf([new TextEncoder().encode("event: token\ndata: {}\n\n")]), {
      status: 200,
      headers: { "Content-Type": "text/event-stream; charset=utf-8" },
    });
  };
  const events = [];
  await postEventStream({ url: "/api/v1/conversations/9/messages/", body: { content: "Hi" }, headers: { Authorization: "Bearer t" }, onEvent: (event) => events.push(event), fetchImpl });
  assert.equal(seen.init.method, "POST");
  assert.equal(seen.init.headers.Accept, "text/event-stream");
  assert.equal(seen.init.headers.Authorization, "Bearer t");
  assert.equal(seen.init.body, JSON.stringify({ content: "Hi" }));
  assert.equal(events.length, 1);
});

test("JSON errors before the stream starts reject with the parsed body", async () => {
  const fetchImpl = async () =>
    new Response(JSON.stringify({ error: { code: "no_ready_documents", message: "No ready documents." } }), {
      status: 409,
      headers: { "Content-Type": "application/json" },
    });
  await assert.rejects(
    postEventStream({ url: "/x", body: {}, onEvent: () => {}, fetchImpl }),
    (error) => error instanceof SseHttpError && error.status === 409 && error.body.error.code === "no_ready_documents",
  );
  const notAStream = async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
  await assert.rejects(postEventStream({ url: "/x", body: {}, onEvent: () => {}, fetchImpl: notAStream }), SseHttpError);
});
