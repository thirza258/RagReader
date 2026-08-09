import { AnalysisResult, RetrievedChunk, WebSocketMessage, DeepAnalysisServiceOptions } from "../interface";
const protocol = window.location.protocol === "https:" ? "wss" : "ws";

export const WS_BASE_URL =
    import.meta.env.VITE_WS_URL ||
    `${protocol}://${window.location.host}`;  

/**
 * Calls the REST endpoint to initiate a deep analysis job.
 * Returns the batch_id used to subscribe to the WebSocket stream.
 */

export const getDeepAnalysisResult = async (
    batchId: string
) => {
    return new WebSocket(`${WS_BASE_URL}/analysis/${batchId}/`);
}
/**
 * Builds the WebSocket URL from a batch_id.
 */
export function buildWebSocketUrl(batchId: string): string {
  return `${WS_BASE_URL}/ws/analysis/${batchId}/`;
}


/**
 * Parses a raw WebSocket message string into a structured object.
 */
export function parseWebSocketMessage(raw: string): WebSocketMessage | null {
  try {
    const jsonStr = raw
      .split("\n")
      .filter((line) => {
        const trimmed = line.trim();
        return trimmed.startsWith("{") || trimmed.startsWith("[");
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
 * Returns null for INITIALIZING status messages (no answer yet).
 */
export function transformToAnalysisResult(
  msg: WebSocketMessage,
  query?: string
): AnalysisResult | null {
  if (msg.status === "INITIALIZING" || msg.status === "COMPLETE") return null;

  if (msg.error) {
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
        retrieval_score: []
      },
      progress: msg.progress ?? 0,
      error: msg.error,
    };
  }

  if (!msg.answer) return null;

  const chunks: RetrievedChunk[] = (msg.context ?? []).map((chunk) => ({
    id: chunk.chunk_id,
    text: chunk.text.trim(),
    score: chunk.score,
  }));

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


/**
 * Opens a WebSocket connection for deep analysis results.
 * Calls onResult for each completed method result.
 * Returns a cleanup function to close the socket.
 */
export function connectDeepAnalysisWebSocket(
  options: DeepAnalysisServiceOptions
): () => void {
  const { url, query, onOpen, onResult, onProgress, onError, onClose } = options;

  const ws = new WebSocket(url);

  ws.onopen = () => {
    if(onOpen) onOpen();
  }

  ws.onmessage = (event: MessageEvent) => {
    const raw: string = typeof event.data === "string" ? event.data : String(event.data);

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
          ws.close();
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
        // Wait for more data if JSON is incomplete
      }
    }
  };

  ws.onerror = (event: Event) => {
    onError?.(event);
  };

  ws.onclose = () => {
    onClose?.();
  };

  

  return () => {
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
      ws.close();
    }
  };
}