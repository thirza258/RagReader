import React from "react";

const STEPS = [
  {
    title: "Document ingestion",
    desc: "A PDF upload, a web page URL, or raw pasted text.",
  },
  {
    title: "Fixed-size chunking",
    desc: "512-character chunks with 50 characters of overlap, applied once at ingest.",
  },
  {
    title: "Dual indexing",
    desc: "openai/text-embedding-3-small vectors alongside a BM25 sparse index.",
  },
  {
    title: "Retrieval and fusion",
    desc: "Cross-encoder reranking (ms-marco-MiniLM-L6-v2) for hybrid; Reciprocal Rank Fusion for the candidate pool.",
  },
  {
    title: "Multi-model execution",
    desc: "Each selected model rewrites the query, retrieves, and generates at temperature 0 through OpenRouter.",
  },
  {
    title: "Scoring",
    desc: "Precision@K, Recall@K, F1@K, ROUGE-L, and three judged answer metrics from Mistral Nemo.",
  },
];

export const ArchitectureFlow: React.FC = () => (
  <ol className="border-t border-border">
    {STEPS.map((step, index) => (
      <li
        key={step.title}
        className="grid gap-1 border-b border-border py-4 sm:grid-cols-[3rem_13rem_1fr] sm:gap-4"
      >
        <span className="font-mono text-sm text-muted-foreground tabular">
          {String(index + 1).padStart(2, "0")}
        </span>
        <span className="font-medium">{step.title}</span>
        <span className="text-sm text-muted-foreground">{step.desc}</span>
      </li>
    ))}
  </ol>
);

export default ArchitectureFlow;
