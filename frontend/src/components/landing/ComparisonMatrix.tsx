import React from "react";
import { Check, X, Minus } from "lucide-react";

export const ComparisonMatrix: React.FC = () => {
  const features = [
    {
      name: "9-Pipeline Evaluation Matrix",
      ragReader: true,
      standardVector: false,
      basicChatbot: false,
      desc: "Simultaneous 3x3 retrieval and model execution",
    },
    {
      name: "Sparse BM25 Keyword Search",
      ragReader: true,
      standardVector: false,
      basicChatbot: false,
      desc: "Exact term, name, and ID matching support",
    },
    {
      name: "Cross-Encoder Reranking",
      ragReader: true,
      standardVector: false,
      basicChatbot: false,
      desc: "MS-MARCO MiniLM cross-encoder candidate scoring",
    },
    {
      name: "Reciprocal Rank Fusion Ground Truth",
      ragReader: true,
      standardVector: false,
      basicChatbot: false,
      desc: "Consensus-derived benchmark candidate pooling",
    },
    {
      name: "Dual Retrieval & Answer Metrics",
      ragReader: true,
      standardVector: false,
      basicChatbot: false,
      desc: "Precision@K, Recall@K, F1@K + ROUGE-L & LLM Judge",
    },
    {
      name: "Live WebSocket Streaming",
      ragReader: true,
      standardVector: "partial",
      basicChatbot: "partial",
      desc: "Real-time results streaming over Channels/Daphne",
    },
    {
      name: "Single API Key (OpenRouter)",
      ragReader: true,
      standardVector: false,
      basicChatbot: false,
      desc: "Unified billing for all LLMs and embeddings",
    },
    {
      name: "Self-Hostable Docker Compose",
      ragReader: true,
      standardVector: false,
      basicChatbot: false,
      desc: "100% open source under MIT License",
    },
  ];

  return (
    <div className="w-full bg-slate-900/80 border border-slate-800 rounded-3xl p-6 sm:p-8 backdrop-blur-xl shadow-2xl overflow-x-auto">
      <table className="w-full text-left border-collapse min-w-[640px]">
        <thead>
          <tr className="border-b border-slate-800 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <th className="pb-4 w-1/3">Feature Capabilities</th>
            <th className="pb-4 text-center text-cyan-400 font-bold text-sm bg-cyan-950/30 py-3 px-4 rounded-t-xl border-x border-t border-cyan-500/30">
              RAGReader
            </th>
            <th className="pb-4 text-center">Standard Vector RAG</th>
            <th className="pb-4 text-center">Basic Document Chat</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/60 text-sm">
          {features.map((item) => (
            <tr key={item.name} className="hover:bg-slate-800/30 transition-colors">
              <td className="py-4 pr-4">
                <span className="font-semibold text-white block">{item.name}</span>
                <span className="text-xs text-slate-400 mt-0.5 block">{item.desc}</span>
              </td>
              <td className="py-4 text-center bg-cyan-950/20 border-x border-cyan-500/20 px-4">
                {item.ragReader ? (
                  <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 mx-auto">
                    <Check className="w-4 h-4" />
                  </span>
                ) : (
                  <X className="w-4 h-4 text-slate-600 mx-auto" />
                )}
              </td>
              <td className="py-4 text-center">
                {item.standardVector === true ? (
                  <Check className="w-4 h-4 text-emerald-400 mx-auto" />
                ) : item.standardVector === "partial" ? (
                  <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-amber-500/10 text-amber-400 mx-auto">
                    <Minus className="w-3.5 h-3.5" />
                  </span>
                ) : (
                  <X className="w-4 h-4 text-slate-600 mx-auto" />
                )}
              </td>
              <td className="py-4 text-center">
                {item.basicChatbot === true ? (
                  <Check className="w-4 h-4 text-emerald-400 mx-auto" />
                ) : item.basicChatbot === "partial" ? (
                  <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-amber-500/10 text-amber-400 mx-auto">
                    <Minus className="w-3.5 h-3.5" />
                  </span>
                ) : (
                  <X className="w-4 h-4 text-slate-600 mx-auto" />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default ComparisonMatrix;
