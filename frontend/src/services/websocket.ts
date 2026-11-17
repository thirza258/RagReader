import type { AnalysisResult, DeepAnalysisServiceOptions, WebSocketMessage } from "../interface";
import { processRawFrame } from "./analysisFrames";
import { authFrame, classifySocketClose, isBatchNotFoundFrame } from "./analysisSocketAuth";
import type { SocketAuthFailure } from "./analysisSocketAuth";

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

export { parseWebSocketMessage, transformToAnalysisResult } from "./analysisFrames";
export type OnResultCallback = (result: AnalysisResult) => void;
export type OnProgressCallback = (method: string, progress: number) => void;
export type OnErrorCallback = (error: Event) => void;

/**
 * Opens a WebSocket connection for deep analysis results.
 * Authenticates with the first frame on every (re)connect, reconnects after
 * unexpected drops, and never retries an authentication failure.
 */
export function connectDeepAnalysisWebSocket(
  options: DeepAnalysisServiceOptions
): () => void {
  const { url, token, onOpen, onError, onClose, onReconnecting, onAuthError } = options;

  let ws: WebSocket | null = null;
  let isManuallyClosed = false;
  let isCompleted = false;
  let retryCount = 0;
  const maxRetries = 3;
  let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  let authFailed = false;

  function failAuth(kind: SocketAuthFailure) {
    if (authFailed) return;
    authFailed = true;
    isCompleted = true;
    onAuthError?.(kind);
  }

  const frameOptions = {
    ...options,
    onServerError: (message: WebSocketMessage) => {
      // The server's answer for a batch that is missing or not ours.
      if (isBatchNotFoundFrame(message)) failAuth("not_found");
      else options.onServerError?.(message);
    },
  };

  function initSocket() {
    if (isManuallyClosed || isCompleted) return;
    if (!token) {
      failAuth("unauthenticated");
      onClose?.();
      return;
    }

    try {
      ws = new WebSocket(url);
    } catch (err) {
      if (!isManuallyClosed) {
        onError?.(err instanceof Event ? err : new Event("error"));
        onClose?.();
      }
      return;
    }

    ws.onopen = () => {
      if (isManuallyClosed) return;
      // Before anything else, on every connect: the server sends nothing
      // about the batch until this frame is accepted.
      ws?.send(authFrame(token));
      onOpen?.();
    };

    ws.onmessage = (event: MessageEvent) => {
      if (isManuallyClosed || isCompleted) return;
      const raw: string = typeof event.data === "string" ? event.data : String(event.data);
      processRawFrame(
        raw, frameOptions,
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

      const kind = classifySocketClose(event.code, isCompleted);
      if (kind === "unauthenticated" || kind === "not_found") {
        failAuth(kind);
        onClose?.();
        return;
      }
      if (kind === "finished") {
        onClose?.();
        return;
      }

      onReconnecting?.();
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
