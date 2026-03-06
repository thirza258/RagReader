// service.ts

const API_BASE_URL = "http://localhost:8000"; // 🔧 Replace with your API base URL
const WS_BASE_URL = "ws://localhost:8000";    // 🔧 Replace with your WS base URL

export interface StartAnalysisResponse {
  message: string;
  batch_id: string;
  expected_count: number;
}

/**
 * Calls the REST endpoint to initiate a deep analysis job.
 * Returns the batch_id used to subscribe to the WebSocket stream.
 */
export async function startDeepAnalysis(
  query: string,
  username: string
): Promise<StartAnalysisResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, username }),
  });

  if (!response.ok) {
    throw new Error(`Failed to start analysis: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Builds the WebSocket URL from a batch_id.
 */
export function buildWebSocketUrl(batchId: string): string {
  return `${WS_BASE_URL}/ws/analysis/${batchId}/`;
}

export interface RetrievedChunk {
  id: string | number;
  label: string;
  text: string;
}

export interface EvaluationMetric {
  label: string;
  value: number;
}

export interface AnalysisResult {
  method: string;
  aiModel: string;
  query: string;
  answer: string;
  retrievedChunks: RetrievedChunk[];
  evaluationMetrics: EvaluationMetric[];
  progress: number;
  error?: string;
}

export interface WebSocketMessage {
  status?: string;
  method?: string;
  query?: string;
  aiModel?: string;
  progress?: number;
  batch_id?: string;
  error?: string;
  answer?: {
    answer: string;
    context: string[];
  };
}

// Static dummy evaluation metrics (to be implemented later)
const DUMMY_METRICS: EvaluationMetric[] = [
  { label: "Retrieval Score", value: 0.85 },
  { label: "Faithfulness Score", value: 0.66 },
  { label: "Answer Relevance", value: 0.75 },
];

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
  if (msg.status === "INITIALIZING" || !msg.answer) {
    return null;
  }

  // Handle error responses
  if (msg.error) {
    return {
      method: msg.method ?? "Unknown",
      aiModel: msg.aiModel ?? "Unknown",
      query: msg.query ?? query ?? "Unknown",
      answer: `Error: ${msg.error}`,
      retrievedChunks: [],
      evaluationMetrics: DUMMY_METRICS,
      progress: msg.progress ?? 0,
      error: msg.error,
    };
  }

  const chunks: RetrievedChunk[] = (msg.answer.context ?? []).map(
    (text, index) => ({
      id: `chunk-${Date.now()}-${index}`,
      label: `Chunk ${index + 1}`,
      text: text.trim(),
    })
  );

  return {
    method: msg.method ?? "Unknown",
    aiModel: msg.aiModel ?? "Unknown",
    query: msg.query ?? query ?? "Unknown",
    answer: msg.answer.answer,
    retrievedChunks: chunks,
    evaluationMetrics: DUMMY_METRICS,
    progress: msg.progress ?? 0,
  };
}

export type OnResultCallback = (result: AnalysisResult) => void;
export type OnProgressCallback = (method: string, progress: number) => void;
export type OnErrorCallback = (error: Event) => void;

export interface DeepAnalysisServiceOptions {
  url: string;
  query?: string;
  onOpen?: () => void;
  onResult: OnResultCallback;
  onProgress?: OnProgressCallback;
  onError?: OnErrorCallback;
  onClose?: () => void;
}

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

export function stopAllWebSockets(cleanups: (() => void)[]) {
  cleanups.forEach((cleanup) => cleanup());
  cleanups.length = 0;
}