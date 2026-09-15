import React, { useCallback, useEffect, useRef, useState } from "react";
import DeepAnalysisCard from "../components/DeepAnalysisCard";
import { buildWebSocketUrl, connectDeepAnalysisWebSocket } from "../services/websocket";
import service from "../services/service";
import { useLocation, useOutletContext, useParams } from "react-router-dom";
import type { DeepResultContextType } from "../types/types";
import type { AnalysisResult, DeepAnalysisConfig, NormalizedChunk } from "../interface";

interface NormalizedResult extends Omit<AnalysisResult, "retrievedChunks"> {
  retrievedChunks: NormalizedChunk[];
}

function normalizeResult(result: AnalysisResult): NormalizedResult {
  return {
    ...result,
    retrievedChunks: result.retrievedChunks.map((chunk, i) => ({
      number: i + 1, id: chunk.id ?? "NULL", text: chunk.text, score: chunk.score,
    })),
  };
}

const STORAGE_KEY = (id: string) => `deep_analysis_results_${id}`;

const DeepResult: React.FC = () => {
  const { conversationId } = useParams<{ conversationId: string }>();
  const { setIds, analysisRequest, stopSignal, setRunState, setModulesAvailable, setSelectedModules } =
    useOutletContext<DeepResultContextType>();
  const location = useLocation();
  const [results, setResults] = useState<NormalizedResult[]>([]);
  const resultsRef = useRef<NormalizedResult[]>([]);
  const [progress, setProgress] = useState<Record<string, number>>({});
  const [isConnected, setIsConnected] = useState(false);
  const [runError, setRunError] = useState("");
  const [activeConfig, setActiveConfig] = useState<DeepAnalysisConfig | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);
  const epochRef = useRef(0);

  const closeSocket = useCallback(() => {
    epochRef.current += 1;
    cleanupRef.current?.();
    cleanupRef.current = null;
  }, []);

  const saveResults = useCallback((updated: NormalizedResult[]) => {
    resultsRef.current = updated;
    setResults(updated);
    if (conversationId) {
      try {
        localStorage.setItem(STORAGE_KEY(conversationId), JSON.stringify(updated));
      } catch {
        // The batch remains available through REST if browser storage is full.
      }
    }
  }, [conversationId]);

  const addOrUpdateResult = useCallback((result: AnalysisResult) => {
    const normalized = normalizeResult(result);
    const previous = resultsRef.current;
    const index = previous.findIndex((r) => r.method === result.method && r.aiModel === result.aiModel);
    saveResults(index < 0 ? [...previous, normalized] : previous.map((r, i) => i === index ? normalized : r));
  }, [saveResults]);

  const restoreConfig = useCallback((config: DeepAnalysisConfig) => {
    setActiveConfig(config);
    setSelectedModules(config.modules ?? []);
  }, [setSelectedModules]);

  const connect = useCallback((batchId: string, query: string, total: number) => {
    closeSocket();
    const epoch = epochRef.current;
    setRunError("");
    const current = () => epochRef.current === epoch;
    const refreshStatus = async () => {
      const data = await service.getAnalysisStatus(batchId);
      if (!current()) return;
      setModulesAvailable(data.modules_available);
      for (const result of data.results) addOrUpdateResult(result);
      return data;
    };
    cleanupRef.current = connectDeepAnalysisWebSocket({
      url: buildWebSocketUrl(batchId), query,
      onOpen: () => {
        if (!current()) return;
        setIsConnected(true);
        setRunState({ isRunning: true, completed: resultsRef.current.length, total });
      },
      onResult: (result) => {
        if (!current()) return;
        addOrUpdateResult(result);
        setRunState({ isRunning: true, completed: resultsRef.current.length, total });
      },
      onProgress: (method, value) => {
        if (current()) setProgress((prev) => ({ ...prev, [method]: value }));
      },
      onError: async () => {
        try {
          const status = await refreshStatus();
          if (status?.is_complete || !current()) return;
        } catch {
          // Report the stream failure if REST is also unavailable.
        }
        if (current()) setRunError("Lost the connection to the analysis stream.");
      },
      onClose: async () => {
        if (!current()) return;
        setIsConnected(false);
        setRunState({ isRunning: false, completed: resultsRef.current.length, total });
        try {
          // Errors and the Stop button must not unlock modules.
          const status = await refreshStatus();
          if (status && !status.is_complete) {
            setRunError("Some variants did not complete. Run Deep Analysis again to retry.");
          }
        } catch {
          if (current()) setRunError("Could not confirm completion. Reload to check the saved analysis.");
        }
      },
    });
  }, [addOrUpdateResult, closeSocket, setModulesAvailable, setRunState]);

  const runAnalysis = useCallback(async (config: DeepAnalysisConfig) => {
    if (!conversationId) return;
    closeSocket();
    const epoch = epochRef.current;
    setIsConnected(false);
    setRunError("");
    setRunState({ isRunning: true, completed: 0, total: config.methods.length * config.models.length });
    try {
      if (config.ground_truth_mode === "pooled") {
        await service.poolGroundTruthChunks(conversationId, {
          top_n: config.pool_top_n, rrf_k: config.rrf_k, config,
        });
        if (epoch !== epochRef.current) return;
      }
      const response = await service.startDeepAnalysis(conversationId, config);
      if (epoch !== epochRef.current) return;
      // Preserve the previous results until the server accepts the new run.
      saveResults([]);
      setProgress({});
      restoreConfig(response.config);
      setModulesAvailable(response.modules_available);
      localStorage.setItem(`batch_id_${conversationId}`, response.batch_id);
      localStorage.setItem("document_id", String(response.document_id));
      setIds({ conversationId, documentId: String(response.document_id) });
      connect(response.batch_id, response.query, response.expected_count);
    } catch (error) {
      if (epoch !== epochRef.current) return;
      setRunError((error as { response?: { data?: { error?: string } } })?.response?.data?.error ?? "Failed to start the analysis.");
      setRunState({ isRunning: false, completed: resultsRef.current.length, total: 0 });
    }
  }, [conversationId, closeSocket, connect, restoreConfig, saveResults, setIds, setModulesAvailable, setRunState]);

  useEffect(() => {
    let cancelled = false;
    async function resume() {
      if (!conversationId) return;
      try {
        const state = location.state as { batch_id?: string; document_id?: string; query?: string } | null;
        // A rerun supersedes the original navigation state, including reloads.
        let batchId = localStorage.getItem(`batch_id_${conversationId}`) || state?.batch_id;
        let documentId = state?.document_id || localStorage.getItem("document_id") || "";
        let query = state?.query || "";
        if (!batchId) {
          const initial = await service.startDeepAnalysis(conversationId);
          if (cancelled) return;
          batchId = initial.batch_id;
          documentId = String(initial.document_id);
          query = initial.query;
        }
        localStorage.setItem(`batch_id_${conversationId}`, batchId);
        const status = await service.getAnalysisStatus(batchId);
        if (cancelled) return;
        saveResults(status.results.map(normalizeResult));
        restoreConfig(status.config);
        setModulesAvailable(status.modules_available);
        setIds({ conversationId, documentId: String(status.document_id ?? documentId) });
        if (status.is_complete) {
          setRunState({ isRunning: false, completed: status.completed, total: status.total });
        } else {
          connect(batchId, query, status.total);
        }
      } catch {
        if (cancelled) return;
        setRunError("Could not load the saved analysis. Reload to try again.");
        setRunState({ isRunning: false, completed: 0, total: 0 });
      }
    }
    resume();
    return () => { cancelled = true; closeSocket(); };
    // Sidebar changes must not reconnect or replace a running batch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  // Nonces represent explicit user actions, including repeat configurations.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (analysisRequest) runAnalysis(analysisRequest.config);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisRequest?.nonce]);
  useEffect(() => {
    if (!stopSignal) return;
    closeSocket();
    setIsConnected(false);
    setRunState({ isRunning: false, completed: resultsRef.current.length, total: 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stopSignal]);
  /* eslint-enable react-hooks/set-state-in-effect */

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border pb-3 text-sm text-muted-foreground">
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className={`inline-block h-1.5 w-1.5 rounded-full ${isConnected ? "bg-status-success" : "bg-border"}`} />
          {isConnected ? "Receiving results" : "Connection closed"}
        </span>
        {activeConfig && (
          <span className="font-mono text-xs">
            Top-K {activeConfig.top_k} · {activeConfig.ground_truth_mode === "pooled" ? `pooled ground truth (top ${activeConfig.pool_top_n})` : "manual ground truth"}
            {" · "}{activeConfig.modules?.length ? `${activeConfig.modules.length} RAG modules enabled` : "Baseline · modules off"}
          </span>
        )}
      </div>
      {runError && <div role="alert" className="border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{runError}</div>}
      {results.length === 0 && isConnected && <div className="py-12 text-center text-sm text-muted-foreground">Waiting for analysis results…</div>}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {results.map((item) => (
          <div key={`${item.method}-${item.aiModel}`} className="overflow-hidden">
            {progress[item.method] !== undefined && progress[item.method] < 100 && (
              <div className="mb-1 h-[3px] w-full overflow-hidden bg-muted"><div className="h-full bg-foreground/60 transition-all" style={{ width: `${progress[item.method]}%` }} /></div>
            )}
            <DeepAnalysisCard method={item.method} aiModel={item.aiModel} query={item.query} answer={item.answer} retrievedChunks={item.retrievedChunks} evaluationMetrics={item.evaluation} />
          </div>
        ))}
      </div>
    </div>
  );
};

export default DeepResult;
