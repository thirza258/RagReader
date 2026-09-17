import type { AnalysisConfigOptions, AnalysisResult, DeepAnalysisConfig, ModuleTrace } from "../interface";
import type { LiveVariantProgress } from "./liveAnalysis";
import { hasRagasEvaluation, RAGAS_ANSWER_METRICS, RAGAS_NOT_RECORDED } from "./evaluation.ts";

export type FlowStatus = "planned" | "running" | "completed" | "skipped" | "fallback" | "unavailable" | "unrecorded" | "failed" | "paused";
export interface FlowStage {
  id: string;
  label: string;
  description: string;
  status: FlowStatus;
  modules: { id: string; label: string; description?: string }[];
  steps: (Omit<ModuleTrace["steps"][number], "status"> & { status: FlowStatus })[];
  liveDetail?: string;
}

export function variantKey(method: string, model: string): string {
  return JSON.stringify([method, model]);
}

export function analysisVariants(config: DeepAnalysisConfig) {
  return config.methods.flatMap((method) => config.models.map((model) => ({ method, model, key: variantKey(method, model) })));
}

/** A completed result confirms the broad phases. Module outcomes always come
 * from its saved trace, never the current sidebar selection or a timer. */
export function buildAnalysisFlow(config: DeepAnalysisConfig, options: AnalysisConfigOptions | null, method: string, result?: AnalysisResult, progress?: LiveVariantProgress, streaming = true): FlowStage[] {
  // Saved successful results are authoritative. Failed attempts can still show
  // the stages actually observed before the error.
  const live = result && !result.error ? undefined : progress;
  const trace = result?.evaluation?.module_trace;
  const enabled = new Set(trace?.enabled ?? config.modules ?? []);
  const catalog = options?.modules ?? [];
  const groups = options?.module_compatibility?.stages;
  const searchIds = groups?.filter((group) => ["routing", "retrieval"].includes(group.id ?? "") || ["Routing", "Queries & retrieval"].includes(group.label)).flatMap((group) => group.modules)
    ?? catalog.filter((module) => ["Routing", "Query", "Retrieval"].includes(module.stage)).map((module) => module.id);
  const evidenceIds = groups?.find((group) => group.id === "evidence" || group.label === "Evidence")?.modules ?? catalog.filter((module) => module.stage === "Refinement").map((module) => module.id);
  const answerIds = groups?.find((group) => group.id === "answer" || group.label === "Answer")?.modules ?? catalog.filter((module) => module.stage === "Generation").map((module) => module.id);
  const direct = (trace?.route ?? live?.route) === "direct";
  const topK = result?.top_k ?? config.top_k;
  const retrieval = enabled.has("rrf_hybrid")
    ? "Combine semantic and keyword search using reciprocal rank fusion. The usual Hybrid reranker is bypassed."
    : method === "Sparse Retrieval"
      ? "Find passages with matching terms using BM25 keyword search."
      : method === "Hybrid Retrieval"
        ? "Combine semantic and keyword results, then rerank the candidate passages."
        : "Find passages with similar meaning using document and question embeddings.";
  const definitions = [
    { id: "question", label: "Question", description: "Start with your question and the document attached to this conversation. Each method/model combination gets its own answer and evaluation.", ids: [] as string[] },
    { id: "search", label: "Search", description: direct ? "Adaptive RAG chose a direct answer. Document retrieval and the remaining search modules were skipped." : `${enabled.size ? "Apply the selected routing and query modules, then search the document. " : "Optimize the search question, falling back to the original question if needed. "}${retrieval} Start with up to ${topK} passages.`, ids: searchIds },
    { id: "evidence", label: "Refine evidence", description: direct ? "The direct route supplied no document evidence to the answer model." : "Combine and refine the source passages. Enabled modules can expand context, remove irrelevant chunks, or search again. Only the final source text becomes evidence.", ids: evidenceIds },
    { id: "answer", label: "Write answer", description: direct ? "Respond directly without making claims about the document." : `Generate the answer from the final evidence.${enabled.has("flare") ? " FLARE can loop back to search for uncertain claims." : ""}${enabled.has("contextual_learning") ? " Contextual Learning adds example Q&A pairs to the prompt." : ""}`, ids: answerIds },
    { id: "evaluate", label: "Evaluate", description: result && !hasRagasEvaluation(result.evaluation) ? `Review the saved retrieval metrics. ${RAGAS_NOT_RECORDED}` : "Compare retrieved chunk IDs with your reference set. Ragas uses the original question, answer, source passages, and reference answer to score answer quality through OpenRouter. Missing inputs or failed metrics remain unavailable.", ids: [] as string[] },
  ];
  return definitions.map(({ ids, ...stage }) => {
    const modules = ids.filter((id) => enabled.has(id)).map((id) => catalog.find((module) => module.id === id) ?? { id, label: id.replace(/_/g, " ") });
    const paused = !streaming || live?.interrupted;
    const steps: FlowStage["steps"] = live
      ? Object.values(live.modules).filter((event) => ids.includes(event.id)).map((event) => ({ module: event.id, label: event.label, status: event.status === "running" && paused ? "paused" : event.status, detail: event.detail, queries: event.queries }))
      : (trace?.steps ?? []).filter((step) => ids.includes(step.module));
    let status: FlowStatus = result ? "completed" : "planned";
    const observed = live?.stages[stage.id];
    if (live) {
      status = observed?.status ?? "planned";
      if (status === "running" && paused) status = "paused";
      if (status === "completed") {
        if (stage.id === "evaluate" && Object.values(live.metrics).some((metric) => metric.status === "unavailable")) status = "unavailable";
        else if (steps.some((step) => step.status === "fallback")) status = "fallback";
      }
    }
    else if (result?.error) status = "unrecorded";
    else if (result) {
      if (direct && ["search", "evidence"].includes(stage.id)) status = "skipped";
      else if (stage.id === "evaluate") {
        const evaluation = result.evaluation;
        const metricStates = RAGAS_ANSWER_METRICS.map((name) => evaluation?.response_evaluation_details?.metrics?.[name]);
        if (!hasRagasEvaluation(evaluation)) status = "unrecorded";
        else if (metricStates.some((metric) => metric?.status === "unavailable")) status = "unavailable";
      } else if (modules.length) {
        if (steps.some((step) => step.status === "fallback")) status = "fallback";
        else if (!steps.length || modules.some((module) => !steps.some((step) => step.module === module.id))) status = "unrecorded";
        else if (stage.id !== "answer" && steps.every((step) => step.status === "skipped")) status = "skipped";
      }
    }
    return { ...stage, modules, steps, status, liveDetail: observed?.detail };
  });
}
