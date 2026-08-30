import React, { useCallback, useEffect, useRef, useState } from "react";
import DeepAnalysisCard from "../components/DeepAnalysisCard";
import {
  buildWebSocketUrl,
  connectDeepAnalysisWebSocket,
} from "../services/websocket";
import service from "../services/service";
import { useLocation, useOutletContext, useParams } from "react-router-dom";
import type { DeepResultContextType } from "../types/types";
import {
  AnalysisResult,
  DeepAnalysisConfig,
  NormalizedChunk,
  StartAnalysisResponse,
} from "../interface";


interface NormalizedResult extends Omit<AnalysisResult, "retrievedChunks"> {
  retrievedChunks: NormalizedChunk[];
}

function normalizeResult(result: AnalysisResult): NormalizedResult {
  return {
    ...result,
    retrievedChunks: result.retrievedChunks.map((chunk, i) => ({
      number: i + 1,
      id: chunk.id ?? `NULL`,
      text: chunk.text,
      score: chunk.score,
    })),
  };
}

const STORAGE_KEY = (id: string) => `deep_analysis_results_${id}`;

const DeepResult: React.FC = () => {
  const { conversationId } = useParams<{ conversationId: string }>();
  const { setIds, analysisRequest, stopSignal, setRunState } =
    useOutletContext<DeepResultContextType>();

  const location = useLocation();

  const [results, setResults] = useState<NormalizedResult[]>(() => {
    if (!conversationId) return [];
    try {
      const stored = localStorage.getItem(STORAGE_KEY(conversationId));
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });
  const [progress, setProgress] = useState<Record<string, number>>({});
  const [isConnected, setIsConnected] = useState(false);
  const [runError, setRunError] = useState("");
  const [activeConfig, setActiveConfig] = useState<DeepAnalysisConfig | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);
  const resultCountRef = useRef(0);

  const closeSocket = useCallback(() => {
    cleanupRef.current?.();
    cleanupRef.current = null;
  }, []);

  const addOrUpdateResult = useCallback(
    (result: AnalysisResult) => {
      if (!conversationId) return;
      const normalized = normalizeResult(result);
      setResults((prev) => {
        const idx = prev.findIndex(
          (r) => r.method === result.method && r.aiModel === result.aiModel,
        );
        const updated =
          idx !== -1
            ? prev.map((r, i) => (i === idx ? normalized : r))
            : [...prev, normalized];

        localStorage.setItem(
          STORAGE_KEY(conversationId),
          JSON.stringify(updated),
        );
        resultCountRef.current = updated.length;
        return updated;
      });
    },
    [conversationId],
  );

  /** Opens the stream for a batch and reports progress back to the sidebar. */
  const connect = useCallback(
    (batchId: string, query: string, total: number) => {
      closeSocket();
      setRunError("");

      const cleanup = connectDeepAnalysisWebSocket({
        url: buildWebSocketUrl(batchId),
        query,
        onOpen: () => {
          setIsConnected(true);
          setRunError("");
          setRunState({ isRunning: true, completed: resultCountRef.current, total });
        },
        onResult: (result) => {
          addOrUpdateResult(result);
          setRunState({
            isRunning: true,
            completed: resultCountRef.current,
            total,
          });
        },
        onProgress: (method, value) => {
          setProgress((prev) => ({ ...prev, [method]: value }));
        },
        onError: async (err) => {
          console.error("WebSocket error:", err);
          setIsConnected(false);
          try {
            const statusData = await service.getAnalysisStatus(batchId);
            if (statusData?.results && Array.isArray(statusData.results)) {
              for (const r of statusData.results) {
                addOrUpdateResult(r);
              }
              if (statusData.is_complete) {
                setRunState({
                  isRunning: false,
                  completed: statusData.completed ?? statusData.results.length,
                  total: statusData.total ?? total,
                });
                return;
              }
            }
          } catch {
            // Ignore fallback failure
          }
          setRunError("Lost the connection to the analysis stream.");
        },
        onClose: () => {
          setIsConnected(false);
          setRunState({ isRunning: false, completed: resultCountRef.current, total });
        },
      });

      cleanupRef.current = cleanup;
    },
    [addOrUpdateResult, closeSocket, setRunState],
  );

  /**
   * Starts a brand-new batch with the given config. In pooled mode the ground
   * truth is rebuilt first, so the retrieval metrics score against the fused
   * ranking rather than a stale manual selection.
   */
  const runAnalysis = useCallback(
    async (config: DeepAnalysisConfig) => {
      if (!conversationId) return;

      closeSocket();
      setResults([]);
      setProgress({});
      resultCountRef.current = 0;
      localStorage.removeItem(STORAGE_KEY(conversationId));
      setRunError("");
      setActiveConfig(config);

      try {
        if (config.ground_truth_mode === "pooled") {
          setRunState({ isRunning: true, completed: 0, total: 0 });
          await service.poolGroundTruthChunks(conversationId, {
            top_n: config.pool_top_n,
          });
        }

        const response: StartAnalysisResponse = await service.startDeepAnalysis(
          conversationId,
          config,
        );

        localStorage.setItem(`batch_id_${conversationId}`, response.batch_id);
        localStorage.setItem("document_id", String(response.document_id));
        localStorage.setItem("conversation_id", conversationId);
        setIds({ conversationId, documentId: String(response.document_id) });

        connect(response.batch_id, response.query, response.expected_count);
      } catch (error) {
        console.error("Error starting deep analysis:", error);
        const message =
          (error as { response?: { data?: { error?: string } } })?.response?.data
            ?.error ?? "Failed to start the analysis.";
        setRunError(message);
        setRunState({ isRunning: false, completed: 0, total: 0 });
      }
    },
    [conversationId, closeSocket, connect, setIds, setRunState],
  );

  // First load: resume the batch we were handed (or already started) rather
  // than kicking off a duplicate run.
  useEffect(() => {
    let cancelled = false;

    async function resume() {
      if (!conversationId) return;

      try {
        const stateData = location.state as {
          batch_id?: string;
          query?: string;
          document_id?: string;
          expected_count?: number;
        } | null;

        let batch_id: string;
        let query: string;
        let document_id: string;
        let expected = 0;

        if (stateData?.batch_id && stateData?.query && stateData?.document_id) {
          ({ batch_id, query, document_id } = stateData);
          expected = stateData.expected_count ?? 0;
        } else {
          const existingBatchId = localStorage.getItem(
            `batch_id_${conversationId}`,
          );
          const existingDocId = localStorage.getItem("document_id") || "";

          if (existingBatchId) {
            batch_id = existingBatchId;
            document_id = existingDocId;
            query = "";

            try {
              const statusData = await service.getAnalysisStatus(existingBatchId);
              if (cancelled) return;

              if (statusData?.results && Array.isArray(statusData.results)) {
                for (const r of statusData.results) {
                  addOrUpdateResult(r);
                }
              }
              expected = statusData?.total ?? 0;
              if (statusData?.is_complete) {
                setIds({ conversationId, documentId: document_id });
                setRunState({
                  isRunning: false,
                  completed: statusData.completed ?? statusData.results?.length ?? 0,
                  total: expected,
                });
                return;
              }
            } catch (err) {
              console.warn("Could not check existing batch status via REST:", err);
            }
          } else {
            const result = await service.startDeepAnalysis(conversationId);
            if (cancelled) return;
            ({ batch_id, query } = result);
            document_id = String(result.document_id);
            expected = result.expected_count;

            localStorage.setItem(`batch_id_${conversationId}`, batch_id);
            localStorage.setItem("document_id", document_id);
            localStorage.setItem("conversation_id", conversationId);
          }
        }

        if (cancelled) return;
        setIds({ conversationId, documentId: document_id });
        connect(batch_id, query, expected);
      } catch (error) {
        console.error("Error starting deep analysis:", error);
        setIsConnected(false);
      }
    }

    resume();

    return () => {
      cancelled = true;
      closeSocket();
    };
    // Deliberately not depending on `connect`: this effect must run once per
    // conversation, not every time a callback identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  // The sidebar's "Run Deep Analysis" button.
  useEffect(() => {
    if (!analysisRequest) return;
    runAnalysis(analysisRequest.config);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisRequest?.nonce]);

  // The sidebar's "Stop Analysis" button.
  useEffect(() => {
    if (stopSignal === 0) return;
    closeSocket();
    setIsConnected(false);
    setRunState({ isRunning: false, completed: resultCountRef.current, total: 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stopSignal]);

  if (!conversationId) {
    return (
      <div className="text-center py-12 text-gray-400">
        No conversation ID provided.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3 text-sm text-gray-500">
        <span className="flex items-center gap-2">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              isConnected ? "bg-green-500 animate-pulse" : "bg-gray-400"
            }`}
          />
          {isConnected ? "Receiving results…" : "Connection closed"}
        </span>

        {activeConfig && (
          <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs">
            Top-K {activeConfig.top_k} ·{" "}
            {activeConfig.ground_truth_mode === "pooled"
              ? `pooled ground truth (top ${activeConfig.pool_top_n})`
              : "manual ground truth"}
          </span>
        )}
      </div>

      {runError && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {runError}
        </div>
      )}

      {results.length === 0 && isConnected && (
        <div className="text-center py-12 text-gray-400 animate-pulse">
          Waiting for analysis results…
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {results.map((item, index) => (
          <div key={`${item.method}-${index}`} className="overflow-hidden">
            {progress[item.method] !== undefined &&
              progress[item.method] < 100 && (
                <div className="mb-1 h-1 w-full bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 transition-all"
                    style={{ width: `${progress[item.method]}%` }}
                  />
                </div>
              )}

            <DeepAnalysisCard
              method={item.method}
              aiModel={item.aiModel}
              query={item.query}
              answer={item.answer}
              retrievedChunks={item.retrievedChunks}
              evaluationMetrics={item.evaluation}
            />
          </div>
        ))}
      </div>
    </div>
  );
};

export default DeepResult;
