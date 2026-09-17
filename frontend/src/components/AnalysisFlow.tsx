import { useState } from "react";
import { ArrowRight, Check, GitBranch, LoaderCircle } from "lucide-react";
import type { AnalysisConfigOptions, AnalysisResult, DeepAnalysisConfig } from "../interface";
import type { AnalysisRunState } from "./DeepSidebar";
import { analysisVariants, buildAnalysisFlow, variantKey } from "../lib/analysisFlow";
import { evaluationMetricEntries, formatMetricValue, hasRagasEvaluation, METRIC_INFO, metricLabel, RAGAS_NOT_RECORDED } from "../lib/evaluation";
import type { LiveAnalysisProgress } from "../lib/liveAnalysis";

interface Props {
  config: DeepAnalysisConfig;
  options: AnalysisConfigOptions | null;
  results: AnalysisResult[];
  runState: AnalysisRunState;
  liveProgress: LiveAnalysisProgress;
  streaming: boolean;
  selectedVariant: string;
  onVariantChange: (key: string) => void;
}

const STATUS_LABELS = {
  planned: "Planned", completed: "Completed", skipped: "Skipped",
  fallback: "Used fallback", unavailable: "Partly unavailable", unrecorded: "Not recorded",
  running: "Running", paused: "Updates paused", failed: "Failed",
};

export default function AnalysisFlow({ config, options, results, runState, liveProgress, streaming, selectedVariant, onVariantChange }: Props) {
  const [selectedStage, setSelectedStage] = useState<{ scope: string; stage: string } | null>(null);
  const variants = analysisVariants(config);
  const activeVariant = variants.find((item) => liveProgress[item.key] && !results.some((result) => variantKey(result.method, result.aiModel) === item.key));
  const variant = variants.find((item) => item.key === selectedVariant) ?? activeVariant ?? variants[0];
  const result = results.find((item) => variantKey(item.method, item.aiModel) === variant?.key);
  const live = !result || result.error ? liveProgress[variant?.key ?? ""] : undefined;
  const selectionScope = `${variant?.key}:${liveProgress[variant?.key ?? ""]?.attemptId ?? result?.batch_id ?? "planned"}`;
  const inspectingStage = selectedStage?.scope === selectionScope;
  const stages = buildAnalysisFlow(config, options, variant?.method ?? "", result, live, streaming);
  const activeStage = stages.find((item) => ["running", "paused", "failed"].includes(item.status));
  const stage = stages.find((item) => inspectingStage && item.id === selectedStage?.stage) ?? activeStage ?? stages[1];
  const trace = result?.evaluation?.module_trace;
  const evaluation = result?.evaluation;
  const details = hasRagasEvaluation(evaluation) ? evaluation?.response_evaluation_details : undefined;
  const topK = result?.top_k ?? config.top_k;
  const metricEntries = [
    ...evaluationMetricEntries(evaluation, "chunk_evaluation"),
    ...evaluationMetricEntries(evaluation, "response_evaluation"),
  ];
  const completed = results.filter((item) => !item.error).length;
  const failed = results.filter((item) => item.error).length;
  const route = trace?.route ?? live?.route;
  const routeLabel = route === "direct" ? "Direct answer · retrieval skipped"
    : route === "multi" ? "Multiple retrieval passes" : route ? "Single retrieval route" : "";
  const queries = trace?.queries ?? live?.queries ?? [];
  const receiving = streaming && !live?.interrupted;
  const activity = live?.activity;
  const activityDetail = activity?.kind === "metric" ? `${metricLabel(activity.id, topK)}: ${activity.detail}` : activity?.detail;

  return (
    <section id="analysis-flow" aria-labelledby="analysis-flow-heading" className="scroll-mt-4 border border-border bg-card">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-border px-4 py-4">
        <div>
          <h2 id="analysis-flow-heading" className="flex items-center gap-2 text-xl font-semibold"><GitBranch size={19} aria-hidden="true" />Analysis flow</h2>
          <p className="mt-1 text-sm text-muted-foreground">Follow a question from search to evaluation. Select a step to explore it.</p>
        </div>
        <p role="status" className="text-xs text-muted-foreground">{completed} of {variants.length} answers saved{failed > 0 ? ` · ${failed} failed` : ""}{runState.isRunning ? " · Running" : ""}</p>
      </header>

      <div className="space-y-4 px-4 py-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="w-full min-w-0 sm:w-auto sm:flex-1 sm:max-w-lg">
            <label htmlFor="flow-variant" className="mb-1.5 block text-xs font-medium">Method and model</label>
            <select id="flow-variant" value={variant?.key ?? ""} onChange={(event) => onVariantChange(event.target.value)} className="w-full min-w-0 border border-input bg-background px-2 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {variants.map((item) => {
                const saved = results.find((entry) => variantKey(entry.method, entry.aiModel) === item.key);
                const current = liveProgress[item.key];
                const state = saved?.error ? "Failed" : saved ? "Saved" : current ? streaming && !current.interrupted ? "Running" : "Updates paused" : runState.isRunning ? "Queued" : "No result";
                return <option key={item.key} value={item.key}>{item.method} · {item.model} · {state}</option>;
              })}
            </select>
          </div>
          {activeVariant && (selectedVariant || inspectingStage) && <button type="button" onClick={() => { onVariantChange(""); setSelectedStage(null); }} className="border border-input px-3 py-2 text-xs font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Follow live progress</button>}
          <span className="text-xs font-medium">{result?.error ? "Incomplete execution" : result ? "Saved result flow" : live ? receiving ? "Live flow" : "Last observed flow" : "Planned flow"}{routeLabel ? ` · ${routeLabel}` : ""}</span>
        </div>

        {live && <div role="status" aria-live="polite" aria-atomic="true" className="border-l-2 border-primary bg-primary/5 px-3 py-2">
          <p className="flex items-center gap-2 text-sm font-medium">{receiving && !result?.error && <LoaderCircle size={14} className="shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />}{result?.error ? "Variant failed" : receiving ? activeStage ? `Live · ${activeStage.label}` : "Saving result" : "Live updates paused"}</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{receiving || result?.error ? activityDetail : "Showing the last received updates. In-flight work may still finish; reload to check saved results."}</p>
        </div>}
        {!result && !live && <p className="text-xs text-muted-foreground">{runState.isRunning ? "Queued for analysis. Live updates will appear when this method/model starts." : "No result was saved for this variant."} Conditional modules may be skipped.</p>}
        {result?.error && <p className="text-sm text-destructive">This variant failed. {live ? "Observed stages are retained in the flow." : "Execution details were not saved."} See the result error below.</p>}

        <ol aria-label="Analysis stages" className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-5">
          {stages.map((item, index) => (
            <li key={item.id} className="relative min-w-0">
              <button type="button" aria-pressed={stage.id === item.id} aria-current={item.status === "running" ? "step" : undefined} aria-controls="flow-step-details" onClick={() => setSelectedStage({ scope: selectionScope, stage: item.id })} className={`h-full w-full border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${stage.id === item.id ? "border-primary bg-primary/5" : "border-border hover:bg-muted"}`}>
                <span className="mb-2 flex items-center justify-between font-mono text-xs text-muted-foreground"><span>0{index + 1}</span>{item.status === "running" ? <LoaderCircle size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : item.status === "completed" ? <Check size={13} aria-hidden="true" /> : index < stages.length - 1 ? <ArrowRight size={13} aria-hidden="true" /> : null}</span>
                <span className="block text-sm font-medium">{item.label}</span>
                <span className={`mt-1 block text-xs ${item.status === "fallback" || item.status === "unavailable" ? "text-status-warning" : "text-muted-foreground"}`}>{STATUS_LABELS[item.status]}</span>
              </button>
            </li>
          ))}
        </ol>

        <div id="flow-step-details" role="region" aria-label={`${stage.label} details`} className="border border-border bg-muted/40 p-4">
          <h3 className="text-base font-semibold">{stage.label}</h3>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{stage.description}</p>
          {stage.liveDetail && <p className="mt-2 text-sm font-medium">{stage.liveDetail}</p>}
          {stage.id === "question" && result && <blockquote className="mt-3 border-l-2 border-primary pl-3 text-sm">{result.query}</blockquote>}
          {stage.modules.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{stage.modules.map((module) => <span key={module.id} title={module.description} className="border border-border bg-background px-2 py-1 text-xs">{module.label}{live && <span className="ml-1 text-muted-foreground">· {STATUS_LABELS[stage.steps.find((step) => step.module === module.id)?.status ?? "planned"]}</span>}</span>)}</div>}
          {stage.steps.length > 0 && (
            <ol aria-label={`${stage.label} execution log`} className="mt-4 space-y-3 border-l border-border pl-4">
              {stage.steps.map((step, index) => (
                <li key={`${step.module}-${index}`}>
                  <p className="text-sm font-medium">{step.label ?? step.module}<span className="ml-2 text-xs font-normal text-muted-foreground">{STATUS_LABELS[step.status]}</span></p>
                  <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{step.detail}</p>
                  {step.queries?.map((query, queryIndex) => <p key={queryIndex} className="mt-1 break-words text-xs italic">{query}</p>)}
                </li>
              ))}
            </ol>
          )}
          {stage.id === "search" && queries.length ? <details className="mt-4 text-sm"><summary className="cursor-pointer font-medium">Search inputs used ({queries.length})</summary><p className="mt-2 text-xs text-muted-foreground">Includes follow-up questions and hypothetical passages used for retrieval. These are search inputs, not source evidence.</p><ol className="mt-2 list-decimal space-y-2 pl-5 text-xs">{queries.map((query, index) => <li key={index} className="break-words">{query}</li>)}</ol></details> : null}
          {stage.id === "evidence" && result && <p className="mt-3 text-sm font-medium">{result.retrievedChunks.length} source passages in the final context · {result.retrievedChunks.reduce((sum, chunk) => sum + chunk.text.length, 0).toLocaleString()} characters</p>}
          {stage.id === "answer" && result && <p className="mt-3 text-sm">Answer model: <span className="break-all font-mono text-xs">{result.aiModel}</span>. Read the answer and its source passages in the result card below.</p>}
          {stage.id === "evaluate" && (
            <div className="mt-4 space-y-3">
              <p className="text-xs font-medium">{details ? `Ragas ${details.version} · OpenRouter · ${details.judge_model}` : result ? RAGAS_NOT_RECORDED : `Ragas · OpenRouter · ${config.judge_model}`}</p>
              {details && <p className="break-words text-xs text-muted-foreground">Response relevance embeddings: {details.embedding_model}</p>}
              <dl className="grid gap-3 md:grid-cols-2">
                {metricEntries.map(([name, value]) => {
                  const metric = live?.metrics[name];
                  const metricState = metric?.status === "running" && !receiving ? "paused" : metric?.status;
                  const reason = details?.metrics[name]?.reason ?? (metric && metric.status !== "completed" ? metric.detail : undefined);
                  const display = result && !result.error ? formatMetricValue(value) : metricState === "completed" ? formatMetricValue(metric?.score) : metricState === "unavailable" ? "Unavailable" : metricState ? STATUS_LABELS[metricState] : "Pending";
                  return <div key={name} className="border-t border-border pt-2">
                    <dt className="flex flex-wrap justify-between gap-2 text-sm font-medium"><span>{metricLabel(name, topK)}</span><span className="font-mono text-xs">{display}</span></dt>
                    <dd className="mt-1 text-xs leading-relaxed text-muted-foreground">{METRIC_INFO[name]?.description}{reason && <span className="mt-1 block text-muted-foreground">{reason}</span>}</dd>
                  </div>
                })}
              </dl>
            </div>
          )}
        </div>
        <p className="text-xs text-muted-foreground">This flow belongs to the saved run configuration. Sidebar changes apply when you run deep analysis again.</p>
      </div>
    </section>
  );
}
