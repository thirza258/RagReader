import React from "react";
import { NormalizedChunk, EvaluationMetric } from "../interface";

interface DeepAnalysisCardProps {
  method: string;
  aiModel: string;
  query: string;
  answer: string;
  retrievedChunks: NormalizedChunk[];
  evaluationMetrics?: EvaluationMetric;
  className?: string;
}

const SECTION_LABEL_MAP: Record<string, string> = {
  chunk_evaluation: "Retrieval",
  response_evaluation: "Answer",
};

const METRIC_LABEL_MAP: Record<string, string> = {
  precision_k: "Precision@K",
  recall_k: "Recall@K",
  f1_k: "F1@K",
  rougeL_precision: "ROUGE-L precision",
  rougeL_recall: "ROUGE-L recall",
  rougeL_f1: "ROUGE-L F1",
  faithfulness: "Faithfulness",
  answer_relevance: "Answer relevance",
  answer_coverage: "Answer coverage",
};

const getMetricLabel = (name: string): string =>
  METRIC_LABEL_MAP[name] ??
  name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const formatMetricValue = (value: number | string): string => {
  const num = typeof value === "string" ? parseFloat(value) : value;
  if (isNaN(num)) return "N/A";
  return (num * 100).toFixed(1) + "%";
};

const DeepAnalysisCard: React.FC<DeepAnalysisCardProps> = ({
  method,
  aiModel,
  query,
  answer,
  retrievedChunks,
  evaluationMetrics,
  className = "",
}) => (
  <article className={`border border-border bg-card ${className}`}>
    <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border px-4 py-3">
      <h3 className="font-serif text-base font-semibold">{method}</h3>
      <span className="font-mono text-xs text-muted-foreground">{aiModel}</span>
    </header>

    <dl className="divide-y divide-border text-sm">
      <div className="px-4 py-3">
        <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Query
        </dt>
        <dd className="mt-1">{query}</dd>
      </div>

      <div className="px-4 py-3">
        <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Generated answer
        </dt>
        <dd className="prose-note mt-1 text-base">{answer}</dd>
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
                        <span key={key} className="text-muted-foreground">
                          {getMetricLabel(key)}{" "}
                          <span className="font-mono text-foreground tabular">
                            {formatMetricValue(value as number)}
                          </span>
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
