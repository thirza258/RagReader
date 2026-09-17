import type { EvaluationMetric } from "../interface";

export const RETRIEVAL_METRICS = ["precision_k", "recall_k", "f1_k"] as const;
export const RAGAS_ANSWER_METRICS = ["faithfulness", "answer_relevancy", "factual_correctness"] as const;
export const RAGAS_NOT_RECORDED = "Ragas answer evaluation was not recorded for this result. Run deep analysis again to calculate it.";

export const METRIC_INFO: Record<string, { label: string; description: string }> = {
  precision_k: { label: "Precision@K", description: "Share of retrieved chunks that match your reference chunk set." },
  recall_k: { label: "Recall@K", description: "Share of your reference chunks that retrieval found." },
  f1_k: { label: "F1@K", description: "Balance between retrieval precision and recall." },
  faithfulness: { label: "Faithfulness", description: "How many answer claims are supported by the actual retrieved evidence." },
  answer_relevancy: { label: "Response relevance", description: "How closely questions generated from the answer match your original question, using remote embeddings." },
  factual_correctness: { label: "Factual correctness (F1)", description: "Balance of correct and complete answer claims compared with your reference answer." },
};

export function metricLabel(name: string, topK?: number): string {
  const label = METRIC_INFO[name]?.label ?? name.replace(/_/g, " ");
  return typeof topK === "number" && Number.isInteger(topK) && topK > 0
    ? label.replace("@K", `@${topK}`)
    : label;
}

export function hasRagasEvaluation(evaluation?: EvaluationMetric): boolean {
  return evaluation?.response_evaluation_details?.framework === "ragas";
}

export function evaluationMetricEntries(
  evaluation: EvaluationMetric | undefined,
  section: "chunk_evaluation" | "response_evaluation",
): [string, number | string | null][] {
  const retrieval = section === "chunk_evaluation";
  const names = retrieval ? RETRIEVAL_METRICS : RAGAS_ANSWER_METRICS;
  const scores = retrieval || hasRagasEvaluation(evaluation) ? evaluation?.[section] : undefined;
  return names.map((name) => [name, scores?.[name] ?? null]);
}

export function formatMetricValue(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "Unavailable";
  const number = typeof value === "string" ? Number(value) : value;
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "Unavailable";
}
