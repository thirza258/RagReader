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

const DeepAnalysisCard: React.FC<DeepAnalysisCardProps> = ({
  method,
  aiModel,
  query,
  answer,
  retrievedChunks,
  evaluationMetrics,
  className = "",
}) => {
  const SECTION_LABEL_MAP: Record<string, string> = {
    chunk_evaluation: "Chunk Evaluation",
    response_evaluation: "Response Evaluation",
  };

  const METRIC_LABEL_MAP: Record<string, string> = {
    precision_k: "Precision@K",
    recall_k: "Recall@K",
    f1_k: "F1@K",
    rougeL_precision: "ROUGE-L Precision",
    rougeL_recall: "ROUGE-L Recall",
    rougeL_f1: "ROUGE-L F1",
      faithfulness: "Faithfulness",
      answer_relevance: "Answer Relevance",
      answer_coverage: "Answer Coverage"
  };

  const getMetricLabel = (name: string): string =>
    METRIC_LABEL_MAP[name] ??
    name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  const formatMetricValue = (value: number): string =>
    (value * 100).toFixed(1) + "%";
  return (
    <div className={`relative ${className}`}>
      <div className="relative z-10 bg-slate-900 border border-slate-700 rounded-2xl p-4 shadow-2xl  ">
        <div className="flex items-center gap-3 mb-4 border-b border-slate-700 pb-4">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-red-500" />
            <div className="w-3 h-3 rounded-full bg-yellow-500" />
            <div className="w-3 h-3 rounded-full bg-green-500" />
          </div>
          <div className="ml-2 text-white font-semibold text-sm">
            {method} - <span className="text-slate-400">{aiModel}</span>
          </div>
        </div>

        <div className="space-y-4">
          <div className="bg-slate-800 p-4 rounded-lg border border-slate-700">
            <div className="text-xs text-slate-400 mb-1 uppercase tracking-wider">
              Query
            </div>
            <div className="text-white font-medium text-sm leading-relaxed">
              {query}
            </div>
          </div>

          <div className="bg-slate-800 p-4 rounded-lg border border-slate-700">
            <div className="text-xs text-slate-400 mb-1 uppercase tracking-wider">
              Generated Answer
            </div>
            <div className="text-white font-medium text-sm leading-relaxed">
              {answer}
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-xs text-slate-400 uppercase tracking-wider">
              Retrieved Context
            </div>

            {retrievedChunks.length > 0 ? (
              retrievedChunks.map((chunk) => (
                <div
                  key={chunk.id}
                  className="bg-slate-800/70 rounded-lg border border-slate-700 overflow-hidden transition-colors hover:bg-slate-800"
                >
                  {/* Header row */}
                  <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-700 bg-slate-900/50">
                    <span className="text-cyan-400 font-mono text-xs">
                      chunk {chunk.number} - ID: {chunk.id}
                    </span>
                    {chunk.score !== undefined && (
                      <span
                        className={`text-xs font-medium px-1.5 py-0.5 rounded-full ${
                          chunk.score >= 0.75
                            ? "bg-emerald-900/50 text-emerald-400"
                            : chunk.score >= 0.5
                              ? "bg-yellow-900/50 text-yellow-400"
                              : "bg-red-900/50 text-red-400"
                        }`}
                      >
                        {" "}
                        Retrieval Score: {(chunk.score * 100).toFixed(1)}%
                      </span>
                    )}
                  </div>

                  {/* Body */}
                  <div className="px-3 py-2 text-sm text-slate-300 leading-relaxed">
                    {chunk.text}
                  </div>
                </div>
              ))
            ) : (
              <div className="text-slate-500 text-xs italic">
                No chunks retrieved.
              </div>
            )}
          </div>

          {evaluationMetrics && (
            <div className="space-y-4">
              <div className="text-xs text-slate-400 uppercase tracking-wider">
                Evaluation
              </div>

              {(["chunk_evaluation", "response_evaluation"] as const).map(
                (section) => {
                  const sectionData = evaluationMetrics[section];
                  if (!sectionData || Object.keys(sectionData).length === 0)
                    return null;

                  return (
                    <div
                      key={section}
                      className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden"
                    >
                      {/* Section header */}
                      <div className="px-3 py-2 border-b border-slate-700 bg-slate-900/50">
                        <span className="text-xs text-slate-400 uppercase tracking-wider font-semibold">
                          {SECTION_LABEL_MAP[section]}
                        </span>
                      </div>

                      {/* Metrics grid */}
                      <div className="grid grid-cols-3 gap-px bg-slate-700">
                        {Object.entries(sectionData).map(([key, value]) => (
                          <div
                            key={key}
                            className="bg-slate-800 p-3 text-center"
                          >
                            <div className="text-xs text-slate-500 mb-1">
                              {getMetricLabel(key)}
                            </div>
                            <div className="text-lg font-bold text-cyan-400">
                              {formatMetricValue(value as number)}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                },
              )}
            </div>
          )}
        </div>
      </div>
      <div className="absolute -inset-4 bg-gradient-to-r from-cyan-600 to-blue-600 opacity-30 blur-2xl -z-10 rounded-full pointer-events-none" />
    </div>
  );
};

export default DeepAnalysisCard;
