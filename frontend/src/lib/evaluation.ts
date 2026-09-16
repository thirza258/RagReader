export const METRIC_INFO: Record<string, { label: string; description: string }> = {
  precision_k: { label: "Precision@K", description: "Share of retrieved chunks that match your reference chunk set." },
  recall_k: { label: "Recall@K", description: "Share of your reference chunks that retrieval found." },
  f1_k: { label: "F1@K", description: "Balance between retrieval precision and recall." },
  faithfulness: { label: "Faithfulness", description: "How many answer claims are supported by the actual retrieved evidence." },
  answer_relevancy: { label: "Response relevance", description: "How closely questions generated from the answer match your original question, using remote embeddings." },
  factual_correctness: { label: "Factual correctness (F1)", description: "Balance of correct and complete answer claims compared with your reference answer." },
  // Saved runs keep their original names and values after the Ragas migration.
  rougeL_precision: { label: "ROUGE-L precision (legacy)", description: "Text overlap from a run saved before Ragas evaluation." },
  rougeL_recall: { label: "ROUGE-L recall (legacy)", description: "Text overlap from a run saved before Ragas evaluation." },
  rougeL_f1: { label: "ROUGE-L F1 (legacy)", description: "Text overlap from a run saved before Ragas evaluation." },
  answer_relevance: { label: "Answer relevance (legacy)", description: "Judge score from a run saved before Ragas evaluation." },
  answer_coverage: { label: "Answer coverage (legacy)", description: "Judge score from a run saved before Ragas evaluation." },
};

export function metricLabel(name: string): string {
  return METRIC_INFO[name]?.label ?? name.replace(/_/g, " ");
}

export function formatMetricValue(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "Unavailable";
  const number = typeof value === "string" ? Number(value) : value;
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "Unavailable";
}
