import type { AnalysisResult, DeepAnalysisServiceOptions } from "../interface";
import { processRawFrame } from "./analysisFrames";

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
 * Handles auto-reconnect and clean teardown.
 */
export function connectDeepAnalysisWebSocket(
  options: DeepAnalysisServiceOptions
): () => void {
  const { url, onOpen, onError, onClose, onReconnecting } = options;

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
        onClose?.();
      }
      return;
    }

    ws.onopen = () => {
      if (!isManuallyClosed) {
        onOpen?.();
      }
    };

    ws.onmessage = (event: MessageEvent) => {
      if (isManuallyClosed || isCompleted) return;
      const raw: string = typeof event.data === "string" ? event.data : String(event.data);
      processRawFrame(
        raw, options,
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
