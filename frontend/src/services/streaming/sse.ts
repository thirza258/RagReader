/**
 * Server-Sent Events over a `fetch` POST.
 *
 * `EventSource` can only GET and cannot send an Authorization header, so the
 * chat stream is read from a fetch body instead. The parser follows the
 * WHATWG event-stream rules (any of CRLF, LF or CR ends a line; `:` lines are
 * comments; `data:` lines join with "\n"), with one deliberate addition: a
 * frame the server left without its closing blank line is still delivered
 * when the stream ends, because the last event of a chat turn matters most.
 *
 * This module has no imports so the tests can load it directly in Node.
 */

export interface ServerSentEvent {
  /** The `event:` field, or "message" when the frame had none. */
  event: string;
  data: string;
  id: string | null;
  retry: number | null;
}

export interface SseParser {
  /** Feed decoded text; returns the events completed by this chunk. */
  push(chunk: string): ServerSentEvent[];
  /** The stream ended: flush a final line and an unterminated frame. */
  end(): ServerSentEvent[];
}

export function createSseParser(): SseParser {
  let buffer = "";
  let sawFirstChunk = false;
  let eventType = "";
  let data = "";
  let hasData = false;
  let lastEventId: string | null = null;
  let retry: number | null = null;

  function dispatch(out: ServerSentEvent[]) {
    if (!hasData) {
      eventType = "";
      return;
    }
    out.push({
      event: eventType || "message",
      data: data.endsWith("\n") ? data.slice(0, -1) : data,
      id: lastEventId,
      retry,
    });
    eventType = "";
    data = "";
    hasData = false;
  }

  function processLine(line: string, out: ServerSentEvent[]) {
    if (line === "") {
      dispatch(out);
      return;
    }
    if (line.startsWith(":")) return; // comment, e.g. ": ping"
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    switch (field) {
      case "event":
        eventType = value;
        break;
      case "data":
        data += `${value}\n`;
        hasData = true;
        break;
      case "id":
        if (!value.includes("\u0000")) lastEventId = value;
        break;
      case "retry":
        if (/^\d+$/.test(value)) retry = Number(value);
        break;
      default:
        break; // unknown fields are ignored
    }
  }

  return {
    push(chunk) {
      const out: ServerSentEvent[] = [];
      if (!chunk) return out;
      buffer += chunk;
      if (!sawFirstChunk) {
        sawFirstChunk = true;
        if (buffer.charCodeAt(0) === 0xfeff) buffer = buffer.slice(1);
      }
      let start = 0;
      for (let i = 0; i < buffer.length; i += 1) {
        const code = buffer.charCodeAt(i);
        if (code === 10 /* \n */) {
          processLine(buffer.slice(start, i), out);
          start = i + 1;
        } else if (code === 13 /* \r */) {
          // A CR at the very end may be the first half of a CRLF split across
          // chunks; wait for the next chunk before deciding.
          if (i === buffer.length - 1) break;
          processLine(buffer.slice(start, i), out);
          if (buffer.charCodeAt(i + 1) === 10) i += 1;
          start = i + 1;
        }
      }
      buffer = buffer.slice(start);
      return out;
    },
    end() {
      const out: ServerSentEvent[] = [];
      if (buffer.length > 0) {
        const rest = buffer.endsWith("\r") ? buffer.slice(0, -1) : buffer;
        buffer = "";
        processLine(rest, out);
      }
      dispatch(out);
      return out;
    },
  };
}

/** Parses a whole event-stream body at once (used by tests and fallbacks). */
export function parseSseText(text: string): ServerSentEvent[] {
  const parser = createSseParser();
  return [...parser.push(text), ...parser.end()];
}

/**
 * Decodes a byte stream and reports every event. Multi-byte characters split
 * across chunks survive because the decoder runs in streaming mode.
 */
export async function readEventStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: ServerSentEvent) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  const parser = createSseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) for (const event of parser.push(decoder.decode(value, { stream: true }))) onEvent(event);
    }
    for (const event of parser.push(decoder.decode())) onEvent(event);
    for (const event of parser.end()) onEvent(event);
  } finally {
    reader.releaseLock();
  }
}

/** A non-2xx (or non-stream) answer received before any event was read. */
export class SseHttpError extends Error {
  status: number;
  /** Parsed JSON when the body was JSON, otherwise the raw text. */
  body: unknown;

  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `The server answered ${status} instead of an event stream.`);
    this.name = "SseHttpError";
    this.status = status;
    this.body = body;
  }
}

export interface PostEventStreamOptions {
  url: string;
  body: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  onEvent: (event: ServerSentEvent) => void;
  /** Injected in tests; defaults to the global `fetch`. */
  fetchImpl?: typeof fetch;
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text().catch(() => "");
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/**
 * POSTs JSON and reads the response as an event stream. Resolves when the
 * server closes the stream; rejects with `SseHttpError` when the response is
 * not a stream, and with the fetch error (an `AbortError` after `abort()`)
 * when the connection fails.
 */
export async function postEventStream(options: PostEventStreamOptions): Promise<void> {
  const doFetch = options.fetchImpl ?? fetch;
  const response = await doFetch(options.url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...options.headers,
    },
    body: JSON.stringify(options.body),
    signal: options.signal,
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) throw new SseHttpError(response.status, await readBody(response));
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("text/event-stream")) {
    throw new SseHttpError(response.status, await readBody(response), "The server did not answer with an event stream.");
  }
  if (!response.body) throw new SseHttpError(response.status, null, "The event stream had no body.");
  await readEventStream(response.body, options.onEvent);
}
