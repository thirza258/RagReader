import { AnalysisResult, RetrievedChunk, WebSocketMessage, DeepAnalysisServiceOptions } from "../interface";

export function getWsBaseUrl(): string {
  const envWs = import.meta.env.VITE_WS_URL;
  if (envWs) {
    let url = envWs.trim();
    if (url.startsWith("http://")) url = "ws://" + url.slice(7);
    else if (url.startsWith("https://")) url = "wss://" + url.slice(8);
    else if (!url.startsWith("ws://") && !url.startsWith("wss://")) {
      const proto = window.location.protocol === "https:" ? "wss://" : "ws://";
      url = proto + url.replace(/^\/+/, "");
    }
    return url.replace(/\/+$/, "");
  }
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}`;
}

export const WS_BASE_URL = getWsBaseUrl();

/**
 * Builds the WebSocket URL from a batch_id.
 */
export function buildWebSocketUrl(batchId: string): string {
  const base = getWsBaseUrl();
  return `${base}/ws/analysis/${batchId}/`;
}

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
    msg.status === "INITIALIZING" ||
    msg.status === "COMPLETE" ||
    msg.status === "CONFIG" ||
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
    };
  }

  if (!msg.answer) return null;

  const rawChunks = msg.context ?? (msg as { retrievedChunks?: unknown[] }).retrievedChunks ?? [];
  const chunks: RetrievedChunk[] = (Array.isArray(rawChunks) ? rawChunks : []).map(
    (chunk: any) => ({
      id: chunk.chunk_id ?? chunk.id ?? "NULL",
      text: (chunk.text ?? "").trim(),
      score: chunk.score,
    })
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
    },
    progress: msg.progress ?? 0,
  };
}

export type OnResultCallback = (result: AnalysisResult) => void;
export type OnProgressCallback = (method: string, progress: number) => void;
export type OnErrorCallback = (error: Event) => void;

function processRawFrame(
  raw: string,
  query: string | undefined,
  onResult: OnResultCallback,
  onProgress?: OnProgressCallback,
  onComplete?: () => void
) {
  // Try direct parse first
  try {
    const msg: WebSocketMessage = JSON.parse(raw.trim());
    if (msg.status === "COMPLETE") {
      onComplete?.();
      return;
    }
    if (msg.progress !== undefined && msg.method && onProgress) {
      onProgress(msg.method, msg.progress);
    }
    const result = transformToAnalysisResult(msg, query);
    if (result) {
      onResult(result);
    }
    return;
  } catch {
    // If not single JSON, try splitting lines
  }

  const lines = raw.split("\n");
  let buffer = "";

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (/^\d{4}-\d{2}-\d{2}T/.test(trimmed)) continue;

    buffer += trimmed;

    try {
      const msg: WebSocketMessage = JSON.parse(buffer);
      buffer = "";

      if (msg.status === "COMPLETE") {
        onComplete?.();
        return;
      }

      if (msg.progress !== undefined && msg.method && onProgress) {
        onProgress(msg.method, msg.progress);
      }

      const result = transformToAnalysisResult(msg, query);
      if (result) {
        onResult(result);
      }
    } catch {
      // Continue buffering
    }
  }
}

/**
 * Opens a WebSocket connection for deep analysis results.
 * Handles auto-reconnect and clean teardown.
 */
export function connectDeepAnalysisWebSocket(
  options: DeepAnalysisServiceOptions
): () => void {
  const { url, query, onOpen, onResult, onProgress, onError, onClose } = options;

  let ws: WebSocket | null = null;
  let isManuallyClosed = false;
  let isCompleted = false;
  let retryCount = 0;
  const maxRetries = 3;
  let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;

  function initSocket() {
    if (isManuallyClosed || isCompleted) return;

    try {
      ws = new WebSocket(url);
    } catch (err) {
      if (!isManuallyClosed) {
        onError?.(err instanceof Event ? err : new Event("error"));
      }
      return;
    }

    ws.onopen = () => {
      retryCount = 0;
      if (!isManuallyClosed) {
        onOpen?.();
      }
    };

    ws.onmessage = (event: MessageEvent) => {
      if (isManuallyClosed) return;
      const raw: string = typeof event.data === "string" ? event.data : String(event.data);
      processRawFrame(
        raw,
        query,
        (res) => {
          if (!isManuallyClosed) onResult(res);
        },
        (method, progress) => {
          if (!isManuallyClosed) onProgress?.(method, progress);
        },
        () => {
          isCompleted = true;
          if (ws) {
            ws.onclose = null;
            ws.close();
          }
          onClose?.();
        }
      );
    };

    ws.onerror = (event: Event) => {
      if (isManuallyClosed) return;
      onError?.(event);
    };

    ws.onclose = (event: CloseEvent) => {
      if (isManuallyClosed) return;

      if (isCompleted || event.code === 1000) {
        onClose?.();
        return;
      }

      // Retry connecting if unexpectedly dropped
      if (retryCount < maxRetries) {
        retryCount++;
        reconnectTimeout = setTimeout(() => {
          if (!isManuallyClosed && !isCompleted) {
            initSocket();
          }
        }, 1500 * retryCount);
      } else {
        onClose?.();
      }
    };
  }

  initSocket();

  return () => {
    isManuallyClosed = true;
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout);
      reconnectTimeout = null;
    }
    if (ws) {
      ws.onopen = null;
      ws.onerror = null;
      ws.onclose = null;
      ws.onmessage = null;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
      ws = null;
    }
  };
}