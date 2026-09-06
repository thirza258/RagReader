import React from "react";

type Support = true | false | "partial";

const FEATURES: {
  name: string;
  desc: string;
  ragReader: Support;
  standardVector: Support;
  basicChatbot: Support;
}[] = [
  {
    name: "Nine-pipeline evaluation matrix",
    desc: "Three retrieval methods × three models in one run",
    ragReader: true,
    standardVector: false,
    basicChatbot: false,
  },
  {
    name: "Sparse BM25 keyword search",
    desc: "Exact terms, names and identifiers survive retrieval",
    ragReader: true,
    standardVector: false,
    basicChatbot: false,
  },
  {
    name: "Cross-encoder reranking",
    desc: "ms-marco-MiniLM scores every candidate against the query",
    ragReader: true,
    standardVector: false,
    basicChatbot: false,
  },
  {
    name: "Pooled ground truth (RRF)",
    desc: "Consensus reference set derived from every retriever",
    ragReader: true,
    standardVector: false,
    basicChatbot: false,
  },
  {
    name: "Retrieval and answer metrics",
    desc: "Precision@K, Recall@K, F1@K, ROUGE-L and a judge model",
    ragReader: true,
    standardVector: false,
    basicChatbot: false,
  },
  {
    name: "Streamed results",
    desc: "Each pipeline reported as it finishes, over a WebSocket",
    ragReader: true,
    standardVector: "partial",
    basicChatbot: "partial",
  },
  {
    name: "Single API key",
    desc: "OpenRouter covers every LLM and the embeddings",
    ragReader: true,
    standardVector: false,
    basicChatbot: false,
  },
  {
    name: "Self-hostable",
    desc: "MIT licensed, one Docker Compose file",
    ragReader: true,
    standardVector: false,
    basicChatbot: false,
  },
];

const MARK: Record<string, string> = {
  true: "✓",
  false: "—",
  partial: "○",
};

const Mark: React.FC<{ value: Support }> = ({ value }) => (
  <span
    className={value === true ? "text-foreground" : "text-muted-foreground"}
    title={value === true ? "Yes" : value === "partial" ? "Partial" : "No"}
  >
    {MARK[String(value)]}
    <span className="sr-only">
      {value === true ? "Yes" : value === "partial" ? "Partial" : "No"}
    </span>
  </span>
);

export const ComparisonMatrix: React.FC = () => (
  <div className="overflow-x-auto">
    <table className="w-full min-w-[36rem] border-t border-border text-sm">
      <caption className="caption-bottom pt-3 text-left text-sm text-muted-foreground">
        Table 1. {MARK.true} supported · {MARK.partial} partial · {MARK.false} not
        supported.
      </caption>
      <thead>
        <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
          <th scope="col" className="py-3 pr-6 font-medium">
            Capability
          </th>
          <th scope="col" className="w-28 py-3 text-center font-medium">
            RAGReader
          </th>
          <th scope="col" className="w-28 py-3 text-center font-medium">
            Vector RAG
          </th>
          <th scope="col" className="w-28 py-3 text-center font-medium">
            Document chat
          </th>
        </tr>
      </thead>
      <tbody>
        {FEATURES.map((item) => (
          <tr key={item.name} className="border-b border-border align-top">
            <th scope="row" className="py-3 pr-6 text-left font-normal">
              <span className="block font-medium">{item.name}</span>
              <span className="block text-xs text-muted-foreground">{item.desc}</span>
            </th>
            <td className="py-3 text-center">
              <Mark value={item.ragReader} />
            </td>
            <td className="py-3 text-center">
              <Mark value={item.standardVector} />
            </td>
            <td className="py-3 text-center">
              <Mark value={item.basicChatbot} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

export default ComparisonMatrix;
