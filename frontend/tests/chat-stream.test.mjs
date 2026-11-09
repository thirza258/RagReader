import assert from "node:assert/strict";
import { test } from "node:test";
import { applyChatStreamEvent, interruptTurn, parseChatStreamEvent, progressLines, startTurn } from "../src/features/chat/lib/chatStream.ts";
import { formatRetrievalSummary } from "../src/features/chat/lib/retrievalSummary.ts";
import { errorFromResponse, toApiError } from "../src/services/api/errors.ts";
import { validateSourceUrl, validateUploadFile } from "../src/features/documents/lib/uploadValidation.ts";

const message = (id, role, extra = {}) => ({ id, conversation_id: 9, role, content: "", status: "streaming", citations: [], retrieval: null, token_usage: null, latency_ms: null, error: null, analysis_turn: null, created_at: "", ...extra });
const frame = (event, data) => ({ event, data: JSON.stringify(data) });
const evidence = (citation_id) => ({ citation_id, document_id: 12, document_title: "Paper", cited: false, text: "…" });

function run(frames) {
  let turn = startTurn("What is RAG?");
  for (const raw of frames) {
    const event = parseChatStreamEvent(raw);
    if (event) turn = applyChatStreamEvent(turn, event);
  }
  return turn;
}

test("a full turn builds stages, sources and the answer, then the final message wins", () => {
  const frames = [
    frame("message.created", { user_message: message(1, "user", { content: "What is RAG?" }), assistant_message: message(2, "assistant") }),
    frame("stage", { id: "rewrite", status: "completed", detail: "", duration_ms: 300 }),
    frame("stage", { id: "retrieve", status: "running", detail: "" }),
  ];
  let turn = run(frames);
  assert.deepEqual(progressLines(turn).map((l) => [l.state, l.text]), [
    ["done", "Question rewritten for search"],
    ["active", "Searching documents…"],
  ]);
  turn = run([
    ...frames,
    frame("stage", { id: "retrieve", status: "completed", detail: "Retrieved 20 candidates", duration_ms: 120 }),
    frame("retrieval", { candidate_count: 20, context_count: 5, citations: [evidence(1), evidence(2)] }),
    frame("stage", { id: "generate", status: "running", detail: "" }),
    frame("token", { delta: "RAG combines " }),
    frame("token", { delta: "retrieval [1]." }),
  ]);
  assert.equal(turn.content, "RAG combines retrieval [1].");
  assert.equal(turn.citations.length, 2);
  assert.deepEqual(progressLines(turn).map((l) => [l.state, l.text]), [
    ["done", "Question rewritten for search"],
    ["done", "Retrieved 20 candidates"],
    ["done", "Selected 5 passages"],
    ["active", "Generating answer…"],
  ]);
  const final = message(2, "assistant", { content: "RAG combines retrieval [1].", status: "complete", citations: [{ ...evidence(1), cited: true }] });
  turn = applyChatStreamEvent(turn, parseChatStreamEvent(frame("message.completed", { message: final })));
  assert.equal(turn.phase, "completed");
  assert.equal(turn.assistantMessage.status, "complete");
  assert.equal(turn.citations[0].cited, true);
  assert.equal(applyChatStreamEvent(turn, { type: "token", delta: "late" }), turn, "events after the end are ignored");
});

test("error events keep the code and the failed message", () => {
  const turn = run([
    frame("message.created", { user_message: message(1, "user"), assistant_message: message(2, "assistant") }),
    frame("error", { error: { code: "index_unavailable", message: "Paper could not be loaded.", retryable: true }, message: message(2, "assistant", { status: "failed" }) }),
  ]);
  assert.equal(turn.phase, "failed");
  assert.deepEqual(turn.error, { code: "index_unavailable", message: "Paper could not be loaded.", retryable: true, stage: null });
  assert.equal(turn.assistantMessage.status, "failed");
});

test("malformed and unknown frames are ignored", () => {
  assert.equal(parseChatStreamEvent({ event: "token", data: "{not json" }), null);
  assert.equal(parseChatStreamEvent({ event: "mystery", data: "{}" }), null);
  assert.equal(parseChatStreamEvent(frame("message.completed", { message: { nope: true } })), null);
});

test("a dropped stream is 'interrupted' once the server has the question", () => {
  const error = { code: "stream_interrupted", message: "Connection lost." };
  assert.equal(interruptTurn(startTurn("q"), error).phase, "failed");
  const started = run([frame("message.created", { user_message: message(1, "user"), assistant_message: message(2, "assistant") })]);
  assert.equal(interruptTurn(started, error).phase, "interrupted");
});

test("footer summary follows the PRD format and drops unknown parts", () => {
  const retrieval = { candidate_count: 20, context_count: 5, cited_count: 3, timings_ms: { total: 2600, first_token: 900 } };
  assert.equal(formatRetrievalSummary(retrieval), "Retrieval: 20 → 5 → 3 cited · 2.6 s · first token 0.9 s");
  assert.equal(formatRetrievalSummary({ candidate_count: 20, context_count: 5 }, 1250), "Retrieval: 20 → 5 · 1.3 s");
  assert.equal(formatRetrievalSummary(null), null);
});

test("API errors keep the envelope's code, message and retry flag", () => {
  const error = errorFromResponse(409, { error: { code: "ingestion_in_progress", message: "Already indexing.", retryable: false, stage: null, details: null } });
  assert.equal(error.code, "ingestion_in_progress");
  assert.equal(error.message, "Already indexing.");
  assert.equal(error.retryable, false);
  const axiosLike = { message: "Request failed", response: { status: 413, data: { message: "Too big" } } };
  assert.equal(toApiError(axiosLike).code, "file_too_large");
  assert.equal(toApiError(axiosLike).message, "Too big");
  assert.equal(toApiError({ name: "AbortError" }).code, "aborted");
});

test("upload checks mirror the backend's types, size and URL rules", () => {
  assert.equal(validateUploadFile({ name: "paper.PDF", size: 1000 }), null);
  assert.equal(validateUploadFile({ name: "notes.markdown", size: 10 }), null);
  assert.equal(validateUploadFile({ name: "slides.pptx", size: 10 }).code, "unsupported_file_type");
  assert.equal(validateUploadFile({ name: "big.pdf", size: 26 * 1024 * 1024 }).code, "file_too_large");
  assert.equal(validateUploadFile({ name: "empty.txt", size: 0 }).code, "empty_file");
  assert.equal(validateSourceUrl("https://example.com/a").url, "https://example.com/a");
  for (const bad of ["ftp://example.com", "http://localhost:8000", "http://10.0.0.1/", "http://user:pw@example.com", "http://[::1]/", "https://example.com:22/"]) {
    assert.ok("problem" in validateSourceUrl(bad), bad);
  }
});
