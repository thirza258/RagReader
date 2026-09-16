import React from "react";
import { NormalizedChunk, EvaluationMetric } from "../interface";
import { formatMetricValue, METRIC_INFO, metricLabel } from "../lib/evaluation";

interface DeepAnalysisCardProps {
  method: string;
  aiModel: string;
  query: string;
  answer: string;
  error?: string;
  errorCode?: string;
  retrievedChunks: NormalizedChunk[];
  evaluationMetrics?: EvaluationMetric;
  className?: string;
  onShowFlow?: () => void;
}

const SECTION_LABEL_MAP: Record<string, string> = {
  chunk_evaluation: "Retrieval",
  response_evaluation: "Answer",
};

const getMetricLabel = (name: string): string =>
  name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const DeepAnalysisCard: React.FC<DeepAnalysisCardProps> = ({
  method,
  aiModel,
  query,
  answer,
  error,
  errorCode,
  retrievedChunks,
  evaluationMetrics,
  className = "",
  onShowFlow,
}) => (
  <article className={`border border-border bg-card ${className}`}>
    <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border px-4 py-3">
      <h3 className="font-serif text-base font-semibold">{method}</h3>
      <span className="font-mono text-xs text-muted-foreground">{aiModel}</span>
    </header>
    {onShowFlow && <button type="button" onClick={onShowFlow} className="mx-4 my-3 text-xs text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">View analysis flow<span className="sr-only"> for {method} · {aiModel}</span></button>}

    {evaluationMetrics?.module_trace && (
      <details className="border-b border-border px-4 py-3 text-sm">
        <summary className="cursor-pointer font-medium">
          Full module execution log · {evaluationMetrics.module_trace.enabled.length} enabled · {evaluationMetrics.module_trace.route} route
        </summary>
        <ul className="mt-3 space-y-3">
          {evaluationMetrics.module_trace.steps.map((step, index) => (
            <li key={`${step.module}-${index}`}>
              <span className="font-medium">{step.label ?? getMetricLabel(step.module)}</span>
              <span className="ml-2 text-xs text-muted-foreground">{step.status}</span>
              <p className="mt-1 text-xs text-muted-foreground">{step.detail}</p>
              {step.queries?.map((query) => <p key={query} className="mt-1 text-xs italic">{query}</p>)}
            </li>
          ))}
        </ul>
      </details>
    )}

    <dl className="divide-y divide-border text-sm">
      <div className="px-4 py-3">
        <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Query
        </dt>
        <dd className="mt-1">{query}</dd>
      </div>

      <div className="px-4 py-3">
        <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {error ? "Analysis failed" : "Generated answer"}
        </dt>
        <dd className={`prose-note mt-1 text-base ${error ? "text-destructive" : ""}`}>{error || answer}</dd>
        {errorCode && <dd className="mt-2 font-mono text-xs text-muted-foreground">Error code: {errorCode}</dd>}
      </div>

      <div className="px-4 py-3">
        <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Retrieved context
        </dt>
        <dd className="mt-2">
          {retrievedChunks.length > 0 ? (
            <ul className="border-t border-border">
              {retrievedChunks.map((chunk) => (
                <li key={chunk.id} className="border-b border-border py-2.5">
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="font-mono text-xs text-muted-foreground">
                      chunk {chunk.number} · {chunk.id}
                    </span>
                    {chunk.score !== undefined && (
                      <span className="font-mono text-xs tabular">
                        {(chunk.score * 100).toFixed(1)}%
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-muted-foreground">{chunk.text}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted-foreground">No chunks retrieved.</p>
          )}
        </dd>
      </div>
    </dl>

    {evaluationMetrics && (
      <div className="border-t border-border">
        {evaluationMetrics.response_evaluation_details && <p className="border-b border-border px-4 py-2 text-xs text-muted-foreground">Ragas · OpenRouter · <span className="break-all">{evaluationMetrics.response_evaluation_details.judge_model}</span></p>}
        {(["chunk_evaluation", "response_evaluation"] as const).map((section) => {
          const sectionData = evaluationMetrics[section];
          if (!sectionData || Object.keys(sectionData).length === 0) return null;

          return (
            <table key={section} className="w-full border-b border-border text-sm last:border-b-0">
              <caption className="sr-only">{SECTION_LABEL_MAP[section]} metrics</caption>
              <tbody>
                <tr>
                  <th
                    scope="row"
                    className="w-24 border-r border-border px-4 py-3 text-left align-top text-xs font-medium uppercase tracking-wide text-muted-foreground"
                  >
                    {SECTION_LABEL_MAP[section]}
                  </th>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-x-6 gap-y-1.5">
                      {Object.entries(sectionData).map(([key, value]) => (
                        <span key={key} className="text-muted-foreground" title={METRIC_INFO[key]?.description}>
                          {metricLabel(key)}{" "}
                          <span className="font-mono text-foreground tabular">
                            {formatMetricValue(value)}
                          </span>
                          {evaluationMetrics.response_evaluation_details?.metrics[key]?.reason && <span className="mt-1 block text-xs text-status-warning">{evaluationMetrics.response_evaluation_details.metrics[key].reason}</span>}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          );
        })}
      </div>
    )}
  </article>
);

export default DeepAnalysisCard;
