import React, { useCallback, useEffect, useRef, useState } from "react";
import DeepAnalysisCard from "../components/DeepAnalysisCard";
import AnalysisFlow from "../components/AnalysisFlow";
import { variantKey } from "../lib/analysisFlow";
import { interruptLiveProgress, updateLiveProgress } from "../lib/liveAnalysis";
import type { LiveAnalysisProgress } from "../lib/liveAnalysis";
import { analysisFailureSummary, analysisRequestId } from "../lib/analysisRequest";
import { errorMessage } from "../lib/utils";
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
  const { setIds, analysisRequest, stopSignal, setRunState, runState, analysisOptions, setModulesAvailable, setSelectedModules } =
    useOutletContext<DeepResultContextType>();
  const location = useLocation();
  const [results, setResults] = useState<NormalizedResult[]>([]);
  const resultsRef = useRef<NormalizedResult[]>([]);
  const [liveProgress, setLiveProgress] = useState<LiveAnalysisProgress>({});
  const [isConnected, setIsConnected] = useState(false);
  const [runError, setRunError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeBatchId, setActiveBatchId] = useState("");
  const [activeConfig, setActiveConfig] = useState<DeepAnalysisConfig | null>(null);
  const [flowVariant, setFlowVariant] = useState("");
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
    setNotice("");
    setActiveBatchId(batchId);
    let serverError = "";
    const current = () => epochRef.current === epoch;
    const refreshStatus = async () => {
      const data = await service.getAnalysisStatus(batchId, conversationId);
      if (!current()) return;
      setModulesAvailable(data.modules_available);
      for (const result of data.results) addOrUpdateResult(result);
      return data;
    };
    cleanupRef.current = connectDeepAnalysisWebSocket({
      url: buildWebSocketUrl(batchId), batchId, query,
      onOpen: () => {
        if (!current()) return;
        setIsConnected(true);
        if (!serverError) setRunError("");
        setRunState({ isRunning: true, completed: resultsRef.current.filter((r) => !r.error).length, total });
      },
      onResult: (result) => {
        if (!current()) return;
        if (result.batch_id !== batchId) return;
        setNotice("");
        addOrUpdateResult(result);
        setRunState({ isRunning: true, completed: resultsRef.current.filter((r) => !r.error).length, total });
      },
      onStageProgress: (message) => {
        if (current()) setLiveProgress((previous) => updateLiveProgress(previous, message, batchId));
      },
      onWaiting: (message) => { if (current()) setNotice(message); },
      onServerError: (message) => {
        if (!current()) return;
        serverError = message.error ?? "The server could not run this analysis.";
        setRunError(serverError);
        setNotice("");
        setLiveProgress(interruptLiveProgress);
      },
      onReconnecting: () => {
        if (!current()) return;
        setIsConnected(false);
        setLiveProgress(interruptLiveProgress);
        setRunError("Connection interrupted. Reconnecting to the analysis stream…");
      },
      onError: async () => {
        if (!current()) return;
        setIsConnected(false);
        setLiveProgress(interruptLiveProgress);
        try {
          const status = await refreshStatus();
          if (status?.is_finished || serverError || !current()) return;
        } catch {
          // Report the stream failure if REST is also unavailable.
        }
        if (current() && !serverError) setRunError("Lost the connection to the analysis stream.");
      },
      onClose: async () => {
        if (!current()) return;
        setIsConnected(false);
        setNotice("");
        setRunState({ isRunning: false, completed: resultsRef.current.filter((r) => !r.error).length, total });
        try {
          // Errors and the Stop button must not unlock modules.
          const status = await refreshStatus();
          if (status) {
            setRunState({ isRunning: false, completed: status.completed, total: status.total });
            if (!serverError) setRunError(status.is_finished
              ? analysisFailureSummary(status.failed, status.total)
              : "Some variants did not finish. Reload to resume the same batch, or run Deep Analysis again.");
          }
        } catch {
          if (current() && !serverError) setRunError("Could not confirm completion. Reload to check the saved analysis.");
        }
      },
    });
  }, [addOrUpdateResult, closeSocket, conversationId, setModulesAvailable, setRunState]);

  const runAnalysis = useCallback(async (config: DeepAnalysisConfig, intent: string) => {
    if (!conversationId) return;
    closeSocket();
    const epoch = epochRef.current;
    setIsConnected(false);
    setRunError("");
    setNotice("");
    setRunState({ isRunning: true, completed: 0, total: config.methods.length * config.models.length });
    try {
      if (config.ground_truth_mode === "pooled") {
        await service.poolGroundTruthChunks(conversationId, {
          top_n: config.pool_top_n, rrf_k: config.rrf_k, config,
        });
        if (epoch !== epochRef.current) return;
      }
      const response = await service.startDeepAnalysis(conversationId, config, analysisRequestId(conversationId, intent));
      if (epoch !== epochRef.current) return;
      // Preserve the previous results until the server accepts the new run.
      saveResults([]);
      setLiveProgress({});
      setFlowVariant("");
      restoreConfig(response.config);
      setModulesAvailable(response.modules_available);
      localStorage.setItem(`batch_id_${conversationId}`, response.batch_id);
      localStorage.setItem("document_id", String(response.document_id));
      setIds({ conversationId, documentId: String(response.document_id) });
      connect(response.batch_id, response.query, response.expected_count);
    } catch (error) {
      if (epoch !== epochRef.current) return;
      setRunError(errorMessage(error, "Failed to start the analysis."));
      setRunState({ isRunning: false, completed: resultsRef.current.filter((r) => !r.error).length, total: 0 });
    }
  }, [conversationId, closeSocket, connect, restoreConfig, saveResults, setIds, setModulesAvailable, setRunState]);

  useEffect(() => {
    let cancelled = false;
    async function resume() {
      if (!conversationId) return;
      setLiveProgress({});
      setFlowVariant("");
      setRunError("");
      setNotice("");
      try {
        const state = location.state as { batch_id?: string; document_id?: string; query?: string } | null;
        // A rerun supersedes the original navigation state, including reloads.
        let batchId = localStorage.getItem(`batch_id_${conversationId}`) || state?.batch_id;
        let documentId = state?.document_id || localStorage.getItem("document_id") || "";
        let query = state?.query || "";
        if (!batchId) {
          const initial = await service.startDeepAnalysis(conversationId, undefined, analysisRequestId(conversationId));
          if (cancelled) return;
          batchId = initial.batch_id;
          documentId = String(initial.document_id);
          query = initial.query;
        }
        localStorage.setItem(`batch_id_${conversationId}`, batchId);
        const status = await service.getAnalysisStatus(batchId, conversationId);
        if (cancelled) return;
        batchId = status.batch_id;
        localStorage.setItem(`batch_id_${conversationId}`, batchId);
        setActiveBatchId(status.batch_id);
        saveResults(status.results.map(normalizeResult));
        restoreConfig(status.config);
        setModulesAvailable(status.modules_available);
        setIds({ conversationId, documentId: String(status.document_id ?? documentId) });
        if (status.is_finished) {
          setRunError(analysisFailureSummary(status.failed, status.total));
          setRunState({ isRunning: false, completed: status.completed, total: status.total });
        } else {
          connect(batchId, query, status.total);
        }
      } catch (error) {
        if (cancelled) return;
        setRunError(errorMessage(error, "Could not load the saved analysis. Reload to try again."));
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
    if (analysisRequest) runAnalysis(analysisRequest.config, `run_${analysisRequest.nonce}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisRequest?.nonce]);
  useEffect(() => {
    if (!stopSignal) return;
    closeSocket();
    setIsConnected(false);
    setNotice("");
    setRunState({ isRunning: false, completed: resultsRef.current.filter((r) => !r.error).length, total: 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stopSignal]);
  /* eslint-enable react-hooks/set-state-in-effect */

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border pb-3 text-sm text-muted-foreground">
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className={`inline-block h-1.5 w-1.5 rounded-full ${isConnected ? "bg-status-success" : "bg-border"}`} />
          {isConnected ? "Receiving results" : runState.isRunning ? "Preparing analysis" : runError ? "Analysis needs attention" : runState.total > 0 && results.filter((result) => !result.error).length >= runState.total ? "Analysis complete" : "Analysis stopped"}
        </span>
        {activeConfig && (
          <span className="font-mono text-xs">
            Top-K {activeConfig.top_k} · {activeConfig.ground_truth_mode === "pooled" ? `pooled ground truth (top ${activeConfig.pool_top_n})` : "manual ground truth"}
            {" · "}{activeConfig.modules?.length ? `${activeConfig.modules.length} RAG modules enabled` : "Baseline · modules off"}
          </span>
        )}
      </div>
      {activeBatchId && <p className="break-all font-mono text-xs text-muted-foreground">Batch {activeBatchId}{results.some((result) => result.error) && ` · ${results.filter((result) => result.error).length} failed`}</p>}
      {notice && <p role="status" className="border border-border p-3 text-sm text-muted-foreground">{notice}</p>}
      {runError && <div role="alert" className="border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{runError}</div>}
      {activeConfig && <AnalysisFlow config={activeConfig} options={analysisOptions} results={results} runState={runState} liveProgress={liveProgress} streaming={isConnected && runState.isRunning} selectedVariant={flowVariant} onVariantChange={setFlowVariant} />}
      {results.length === 0 && isConnected && <div className="py-12 text-center text-sm text-muted-foreground">Waiting for analysis results…</div>}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {results.map((item) => (
          <div key={`${item.method}-${item.aiModel}`} className="overflow-hidden">
            <DeepAnalysisCard method={item.method} aiModel={item.aiModel} query={item.query} answer={item.answer} error={item.error} errorCode={item.error_code} retrievedChunks={item.retrievedChunks} evaluationMetrics={item.evaluation} topK={item.top_k ?? activeConfig?.top_k} onShowFlow={() => {
              setFlowVariant(variantKey(item.method, item.aiModel));
              const flow = document.getElementById("analysis-flow");
              if (flow) flow.closest("main")?.scrollTo({ top: flow.offsetTop - 16 });
              document.getElementById("flow-variant")?.focus({ preventScroll: true });
            }} />
          </div>
        ))}
      </div>
    </div>
  );
};

export default DeepResult;
