import React, { useEffect, useState, useRef } from "react";
import DeepAnalysisCard from "../components/DeepAnalysisCard";
import {
  buildWebSocketUrl,
  connectDeepAnalysisWebSocket,
  AnalysisResult,
} from "../services/websocket";
import  service from "../services/service";


const QUERY = "What is the Battle of Surabaya?"; 

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

// ── Component ─────────────────────────────────────────────────────────────────
const DeepResult: React.FC = () => {
  const [results, setResults] = useState<NormalizedResult[]>([]);
  const [progress, setProgress] = useState<Record<string, number>>({});
  const [isConnected, setIsConnected] = useState(false);
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
      
        const username = localStorage.getItem("username") || "anonymous";
        const { batch_id } = await service.startDeepAnalysis(QUERY, username);

        if (cancelled) return;

   
        const wsUrl = buildWebSocketUrl(batch_id);
        setIsConnected(true);

        cleanupRef.current = connectDeepAnalysisWebSocket({
          url: wsUrl,
          query: QUERY,

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
      } catch (error) {
        console.error("Error starting deep analysis:", error);
        setIsConnected(false);
      }
    }

    run();

    return () => {
      cancelled = true;
      cleanupRef.current?.();
    };
  }, []);

  return (
    <div className="space-y-6">
      {/* Connection status indicator */}
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <span
          className={`inline-block w-2 h-2 rounded-full ${
            isConnected ? "bg-green-500 animate-pulse" : "bg-gray-400"
          }`}
        />
        {isConnected ? "Receiving results…" : "Connection closed"}
      </div>

      {/* Loading state */}
      {results.length === 0 && isConnected && (
        <div className="text-center py-12 text-gray-400 animate-pulse">
          Waiting for analysis results…
        </div>
      )}

      {/* Result cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {results.map((item, index) => (
          <div key={`${item.method}-${index}`} className="overflow-hidden">
            {/* Optional per-method progress bar */}
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
              query={item.query || QUERY}
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