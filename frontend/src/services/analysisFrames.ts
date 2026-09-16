import type { AnalysisResult, RetrievedChunk, WebSocketMessage, DeepAnalysisServiceOptions } from "../interface";
import { isAnalysisProgressMessage } from "../lib/liveAnalysis.ts";

/**
 * Parses a raw WebSocket message string into a structured object.
 */
export function parseWebSocketMessage(raw: string): WebSocketMessage | null {
  try {
    const trimmed = raw.trim();
    if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
      return JSON.parse(trimmed);
    }
    const jsonStr = raw
      .split("\n")
      .filter((line) => {
        const t = line.trim();
        return t.startsWith("{") || t.startsWith("[");
      })
      .join("\n");

    if (!jsonStr) return null;
    return JSON.parse(jsonStr);
  } catch {
    return null;
  }
}

/**
 * Transforms a parsed WebSocket message into an AnalysisResult.
 * Returns null for INITIALIZING, CONFIG, REPLAYING, or COMPLETE status messages.
 */
export function transformToAnalysisResult(
  msg: WebSocketMessage,
  query?: string
): AnalysisResult | null {
  if (
    msg.status === "STAGE_PROGRESS" ||
    msg.status === "INITIALIZING" ||
    msg.status === "COMPLETE" ||
    msg.status === "CONFIG" ||
    msg.status === "ERROR" ||
    msg.status === "WAITING" ||
    msg.status === "REPLAYING"
  ) {
    return null;
  }

  if (msg.error && msg.method) {
    return {
      batch_id: msg.batch_id ?? "Unknown",
      method: msg.method ?? "Unknown",
      aiModel: msg.aiModel ?? "Unknown",
      query: msg.query ?? query ?? "Unknown",
      answer: `Error: ${msg.error}`,
      retrievedChunks: [],
      evaluation: {
        chunk_evaluation: {},
        response_evaluation: {},
        retrieval_score: [],
      },
      progress: msg.progress ?? 0,
      error: msg.error,
      error_code: msg.error_code,
      retryable: msg.retryable,
    };
  }

  if (!msg.answer) return null;

  const rawChunks = msg.context ?? (msg as { retrievedChunks?: unknown[] }).retrievedChunks ?? [];
  // Chunks arrive from the server under either spelling of the id.
  type RawChunk = {
    chunk_id?: string | number;
    id?: string | number;
    text?: string;
    score?: number;
  };
  const chunks: RetrievedChunk[] = (Array.isArray(rawChunks) ? rawChunks : []).map(
    (chunk) => {
      const raw = (chunk ?? {}) as RawChunk;
      return {
        id: raw.chunk_id ?? raw.id ?? "NULL",
        text: (raw.text ?? "").trim(),
        score: raw.score,
      };
    }
  );

  return {
    batch_id: msg.batch_id ?? "Unknown",
    method: msg.method ?? "Unknown",
    aiModel: msg.aiModel ?? "Unknown",
    query: msg.query ?? query ?? "Unknown",
    answer: msg.answer,
    retrievedChunks: chunks,
    evaluation: {
      chunk_evaluation: msg.evaluation?.chunk_evaluation ?? {},
      response_evaluation: msg.evaluation?.response_evaluation ?? {},
      retrieval_score: msg.evaluation?.retrieval_score ?? [],
      module_trace: msg.evaluation?.module_trace,
      response_evaluation_details: msg.evaluation?.response_evaluation_details,
    },
    progress: msg.progress ?? 0,
  };
}

/** Dispatch status frames separately: live stages are never saved results. */
export function processRawFrame(raw: string, options: Pick<DeepAnalysisServiceOptions, "batchId" | "query" | "onResult" | "onProgress" | "onStageProgress" | "onServerError" | "onWaiting">, onComplete?: () => void) {
  function dispatch(message: WebSocketMessage) {
    if (options.batchId && message.batch_id && message.batch_id !== options.batchId) return false;
    if (message.status === "ERROR" || (message.error && !message.method)) {
      options.onServerError?.(message);
      onComplete?.();
      return true;
    }
    if (message.status === "WAITING") {
      options.onWaiting?.(message.message ?? "This batch is already running. Following its progress…");
      return false;
    }
    if (message.status === "COMPLETE") {
      onComplete?.();
      return true;
    }
    if (message.status === "STAGE_PROGRESS") {
      if (isAnalysisProgressMessage(message)) options.onStageProgress?.(message);
      return false;
    }
    if (message.progress !== undefined && message.method) options.onProgress?.(message.method, message.progress);
    const result = transformToAnalysisResult(message, options.query);
    if (result) options.onResult(result);
    return false;
  }
  let message: WebSocketMessage | undefined;
  try { message = JSON.parse(raw.trim()); } catch { /* Try newline-delimited frames below. */ }
  if (message && typeof message === "object") {
    dispatch(message);
    return;
  }
  let buffer = "";
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || /^\d{4}-\d{2}-\d{2}T/.test(trimmed)) continue;
    buffer += trimmed;
    let parsed: WebSocketMessage;
    try { parsed = JSON.parse(buffer); } catch { continue; }
    buffer = "";
    if (parsed && typeof parsed === "object" && dispatch(parsed)) return;
  }
}
