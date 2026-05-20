import React, { useEffect, useState, useRef } from "react";
import DeepAnalysisCard from "../components/DeepAnalysisCard";
import {
  buildWebSocketUrl,
  connectDeepAnalysisWebSocket,
} from "../services/websocket";
import service from "../services/service";
import { useLocation, useOutletContext, useParams } from "react-router-dom";
import type { DeepResultContextType } from "../types/types";
import { AnalysisResult, NormalizedChunk } from "../interface";


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
  const { setIds } = useOutletContext<DeepResultContextType>();

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
  const cleanupRef = useRef<(() => void) | null>(null);

  if (!conversationId) {
    return (
      <div className="text-center py-12 text-gray-400">
        No conversation ID provided.
      </div>
    );
  }

  const addOrUpdateResult = (result: AnalysisResult) => {
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
      return updated;
    });
  };
  
  useEffect(() => {
    let cancelled = false;
    let wsCleanup: (() => void) | null = null;

    async function run() {
      if (!conversationId) return;

      try {
        const stateData = location.state as {
          batch_id?: string;
          query?: string;
          document_id?: string;
        } | null;

        let batch_id: string;
        let query: string;
        let document_id: string;

        if (stateData?.batch_id && stateData?.query && stateData?.document_id) {
          ({ batch_id, query, document_id } = stateData);
        } else {
          const existingBatchId = localStorage.getItem(
            `batch_id_${conversationId}`,
          );
          if (existingBatchId) return;

          const result = await service.startDeepAnalysis(conversationId);
          if (cancelled) return;
          ({ batch_id, query, document_id } = result);

          localStorage.setItem(`batch_id_${conversationId}`, batch_id);
          localStorage.setItem("document_id", document_id);
          localStorage.setItem("conversation_id", conversationId);
        }

        setIds({ conversationId, documentId: document_id });

        const wsUrl = buildWebSocketUrl(batch_id);

        wsCleanup = connectDeepAnalysisWebSocket({
          url: wsUrl,
          query,
          onOpen: () => setIsConnected(true),
          onResult: (result) => {
            addOrUpdateResult(result);
          },
          onProgress: (method, value) => {
            setProgress((prev) => ({ ...prev, [method]: value }));
          },
          onError: (err) => {
            console.error("WebSocket error:", err);
            setIsConnected(false);
          },
          onClose: () => setIsConnected(false),
        });

        cleanupRef.current = wsCleanup;
      } catch (error) {
        console.error("Error starting deep analysis:", error);
        setIsConnected(false);
      }
    }

    run();

    return () => {
      cancelled = true;
      wsCleanup?.();
      cleanupRef.current = null;
    };
  }, [conversationId, setIds]);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <span
          className={`inline-block w-2 h-2 rounded-full ${
            isConnected ? "bg-green-500 animate-pulse" : "bg-gray-400"
          }`}
        />
        {isConnected ? "Receiving results…" : "Connection closed"}
      </div>

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
