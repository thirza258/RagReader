import React, { useEffect, useState, useRef } from "react";
import DeepAnalysisCard from "../components/DeepAnalysisCard";
import {
  buildWebSocketUrl,
  connectDeepAnalysisWebSocket,
  AnalysisResult,
} from "../services/websocket";
import service from "../services/service";
import { useParams } from "react-router-dom";

interface NormalizedChunk {
  id: string | number;
  label: string;
  text: string;
}

interface NormalizedResult extends Omit<AnalysisResult, "retrievedChunks"> {
  retrievedChunks: NormalizedChunk[];
  modelAgreement: { modelName: string; status: "AGREE" | "NEUTRAL" | "DISAGREE" }[];
}

function normalizeResult(result: AnalysisResult): NormalizedResult {
  return {
    ...result,
    retrievedChunks: result.retrievedChunks.map((chunk, i) => ({
      id: chunk.id ?? `chunk-${i}`,
      label: chunk.label || `Chunk ${i + 1}`,
      text: chunk.text,
    })),
    modelAgreement: [],
  };
}


const DeepResult: React.FC = () => {
  const [results, setResults] = useState<NormalizedResult[]>([]);
  const [progress, setProgress] = useState<Record<string, number>>({});
  const [isConnected, setIsConnected] = useState(false);
  const cleanupRef = useRef<(() => void) | null>(null);

  const { conversationId } = useParams<{ conversationId: string }>();

  if (!conversationId) {
    return (
      <div className="text-center py-12 text-gray-400">
        No conversation ID provided.
      </div>
    );
  }

  useEffect(() => {
  let cancelled = false;
  let wsCleanup: (() => void) | null = null;

  async function run() {
    try {
      if (!conversationId) return;
      const { batch_id, query } = await service.startDeepAnalysis(conversationId);

      // ✅ Check AFTER the async call — StrictMode unmounts before this resolves
      if (cancelled) return;

      const wsUrl = buildWebSocketUrl(batch_id);

      wsCleanup = connectDeepAnalysisWebSocket({
        url: wsUrl,
        query,
        onOpen: () => setIsConnected(true),
        onResult: (result) => {
          const normalized = normalizeResult(result);
          setResults((prev) => {
            const idx = prev.findIndex((r) => r.method === result.method);
            if (idx !== -1) {
              const updated = [...prev];
              updated[idx] = normalized;
              return updated;
            }
            return [...prev, normalized];
          });
        },
        onProgress: (method, value) => {
          setProgress((prev) => ({ ...prev, [method]: value }));
        },
        onError: (err) => {
          console.error("WebSocket error:", err);
          setIsConnected(false);
        },
        onClose: () => {
          setIsConnected(false);
        },
      });

      // ✅ Assign to ref AFTER creation so cleanup can find it
      cleanupRef.current = wsCleanup;

    } catch (error) {
      console.error("Error starting deep analysis:", error);
      setIsConnected(false);
    }
  }

  run();

  return () => {
    cancelled = true;
    // ✅ Use local variable, not ref — ref may not be set yet
    wsCleanup?.();
    cleanupRef.current = null;
  };
}, [conversationId]);

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
              evaluationMetrics={item.evaluationMetrics}
            />
          </div>
        ))}
      </div>
    </div>
  );
};

export default DeepResult;