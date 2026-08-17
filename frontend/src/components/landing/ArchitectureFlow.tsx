import React from "react";
import { FileText, Scissors, Database, GitMerge, Bot, Award, ArrowRight } from "lucide-react";

export const ArchitectureFlow: React.FC = () => {
  const steps = [
    {
      step: "01",
      title: "Document Ingestion",
      desc: "PDF upload, web URL scraping, or raw text input.",
      icon: FileText,
      color: "from-blue-500 to-cyan-500",
    },
    {
      step: "02",
      title: "Fixed-Size Chunking",
      desc: "512-character chunks with 50-character overlap.",
      icon: Scissors,
      color: "from-cyan-500 to-teal-500",
    },
    {
      step: "03",
      title: "Dual Indexing",
      desc: "openai/text-embedding-3-small vectors & BM25 sparse index.",
      icon: Database,
      color: "from-teal-500 to-emerald-500",
    },
    {
      step: "04",
      title: "RRF Candidate Pooler",
      desc: "Cross-encoder reranking (ms-marco-MiniLM-L6-v2) & candidate pooling.",
      icon: GitMerge,
      color: "from-purple-500 to-pink-500",
    },
    {
      step: "05",
      title: "Multi-LLM Execution",
      desc: "OpenRouter multi-model pipeline execution (GPT-4o mini, Gemini 3, Claude Haiku).",
      icon: Bot,
      color: "from-pink-500 to-rose-500",
    },
    {
      step: "06",
      title: "9-Metric Scoring",
      desc: "Precision@K, Recall@K, ROUGE-L, & Mistral Nemo judge faithfulness.",
      icon: Award,
      color: "from-amber-500 to-orange-500",
    },
  ];

  return (
    <div className="w-full">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {steps.map((item, index) => {
          const Icon = item.icon;
          return (
            <div
              key={item.step}
              className="relative p-6 rounded-2xl bg-slate-900/60 border border-slate-800 hover:border-cyan-500/40 transition-all duration-300 group shadow-lg"
            >
              <div className="flex items-center justify-between mb-4">
                <span className="text-xs font-mono font-bold text-slate-500 uppercase tracking-wider">
                  Phase {item.step}
                </span>
                <div
                  className={`w-10 h-10 rounded-xl bg-gradient-to-br ${item.color} flex items-center justify-center text-white shadow-md group-hover:scale-110 transition-transform`}
                >
                  <Icon className="w-5 h-5" />
                </div>
              </div>

              <h4 className="text-lg font-bold text-white mb-2">{item.title}</h4>
              <p className="text-sm text-slate-400 leading-relaxed">{item.desc}</p>

              {index < steps.length - 1 && (
                <div className="hidden lg:block absolute -right-3 top-1/2 -translate-y-1/2 z-10">
                  <ArrowRight className="w-5 h-5 text-slate-700 group-hover:text-cyan-400 transition-colors" />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default ArchitectureFlow;
