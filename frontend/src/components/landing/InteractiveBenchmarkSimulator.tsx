import React, { useState } from "react";
import {
  Database,
  Library,
  Layers,
  Sparkles,
  Zap,
  CheckCircle2,
  Sliders,
  RotateCcw,
  BarChart3,
  Bot,
  FileText,
  Search,
} from "lucide-react";



const SAMPLE_DOCS = [
  {
    title: "Battle of Surabaya (1945)",
    category: "Historical Document",
    defaultQuery: "What caused the Battle of Surabaya and how is it commemorated?",
    data: {
      dense: {
        "GPT-4o mini": {
          precision: 0.6,
          recall: 0.75,
          f1: 0.667,
          rougeL: 0.412,
          faithfulness: 0.8,
          relevance: 0.8,
          coverage: 0.75,
          answer:
            "The Battle of Surabaya in November 1945 began after tensions escalated following the murder of Brigadier A. W. S. Mallaby. Indonesian militias fought British-led troops, resulting in heavy casualties. It is commemorated annually as Heroes' Day (Hari Pahlawan).",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "89.2%",
            },
            {
              id: 2,
              text: "Indonesian pro-independence fighters and militias resisted British and Indian Allied troops in fierce urban fighting.",
              score: "82.5%",
            },
            {
              id: 3,
              text: "The conflict resulted in heavy loss of life and became a national symbol of resistance, celebrated annually as Heroes' Day on November 10.",
              score: "78.1%",
            },
          ],
        },
        "Gemini 3 Flash": {
          precision: 0.6,
          recall: 0.75,
          f1: 0.667,
          rougeL: 0.435,
          faithfulness: 0.85,
          relevance: 0.82,
          coverage: 0.8,
          answer:
            "Indonesian independence forces confronted Allied forces in Surabaya after Brigadier Mallaby's death in late 1945. The intense resistance turned into a turning point for national sovereignty, honored every November 10th as Heroes' Day.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "89.2%",
            },
            {
              id: 2,
              text: "Indonesian pro-independence fighters and militias resisted British and Indian Allied troops in fierce urban fighting.",
              score: "82.5%",
            },
            {
              id: 3,
              text: "The conflict resulted in heavy loss of life and became a national symbol of resistance, celebrated annually as Heroes' Day on November 10.",
              score: "78.1%",
            },
          ],
        },
        "Claude Haiku 4.5": {
          precision: 0.6,
          recall: 0.75,
          f1: 0.667,
          rougeL: 0.448,
          faithfulness: 0.88,
          relevance: 0.85,
          coverage: 0.82,
          answer:
            "The battle erupted in November 1945 following the assassination of Brigadier Mallaby. Indonesian militias fought Allied forces fiercely, making Surabaya a landmark event now honored as National Heroes' Day.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "89.2%",
            },
            {
              id: 2,
              text: "Indonesian pro-independence fighters and militias resisted British and Indian Allied troops in fierce urban fighting.",
              score: "82.5%",
            },
            {
              id: 3,
              text: "The conflict resulted in heavy loss of life and became a national symbol of resistance, celebrated annually as Heroes' Day on November 10.",
              score: "78.1%",
            },
          ],
        },
      },
      sparse: {
        "GPT-4o mini": {
          precision: 0.4,
          recall: 0.5,
          f1: 0.444,
          rougeL: 0.38,
          faithfulness: 0.75,
          relevance: 0.7,
          coverage: 0.65,
          answer:
            "BM25 keyword matching found chunks referencing 'Surabaya', 'Brigadier Mallaby', and 'November 10'. The clash led to significant battle casualties and Heroes' Day commemoration.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "14.8 BM25",
            },
            {
              id: 5,
              text: "Surabaya was a major industrial center in East Java with strategic port facilities during WWII.",
              score: "11.2 BM25",
            },
          ],
        },
        "Gemini 3 Flash": {
          precision: 0.4,
          recall: 0.5,
          f1: 0.444,
          rougeL: 0.395,
          faithfulness: 0.78,
          relevance: 0.72,
          coverage: 0.68,
          answer:
            "Keyword search matched exact terms for Mallaby and Surabaya. The fighting in November 1945 is commemorated as Heroes' Day across Indonesia.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "14.8 BM25",
            },
            {
              id: 5,
              text: "Surabaya was a major industrial center in East Java with strategic port facilities during WWII.",
              score: "11.2 BM25",
            },
          ],
        },
        "Claude Haiku 4.5": {
          precision: 0.4,
          recall: 0.5,
          f1: 0.444,
          rougeL: 0.405,
          faithfulness: 0.8,
          relevance: 0.75,
          coverage: 0.7,
          answer:
            "Sparse BM25 retrieval retrieved historical entries containing exact names. Brigadier Mallaby's death triggered the conflict, now remembered as Heroes' Day on November 10.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "14.8 BM25",
            },
            {
              id: 5,
              text: "Surabaya was a major industrial center in East Java with strategic port facilities during WWII.",
              score: "11.2 BM25",
            },
          ],
        },
      },
      hybrid: {
        "GPT-4o mini": {
          precision: 0.8,
          recall: 1.0,
          f1: 0.889,
          rougeL: 0.512,
          faithfulness: 0.95,
          relevance: 0.94,
          coverage: 0.92,
          answer:
            "Hybrid retrieval combined vector semantic similarity with BM25 keyword matching, reranked by the cross-encoder. It pinpointed Brigadier A. W. S. Mallaby's death as the key trigger of the November 1945 battle and highlighted Heroes' Day (Hari Pahlawan) on November 10.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "94.6% Reranked",
            },
            {
              id: 3,
              text: "The conflict resulted in heavy loss of life and became a national symbol of resistance, celebrated annually as Heroes' Day on November 10.",
              score: "91.2% Reranked",
            },
            {
              id: 2,
              text: "Indonesian pro-independence fighters and militias resisted British and Indian Allied troops in fierce urban fighting.",
              score: "88.4% Reranked",
            },
          ],
        },
        "Gemini 3 Flash": {
          precision: 0.8,
          recall: 1.0,
          f1: 0.889,
          rougeL: 0.53,
          faithfulness: 0.96,
          relevance: 0.95,
          coverage: 0.94,
          answer:
            "Cross-encoder reranking fused dense vectors and BM25 keywords, giving Gemini full context. The clash erupted over Brigadier Mallaby's assassination in Surabaya, sparking intense urban resistance that is celebrated every November 10 as Heroes' Day.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "94.6% Reranked",
            },
            {
              id: 3,
              text: "The conflict resulted in heavy loss of life and became a national symbol of resistance, celebrated annually as Heroes' Day on November 10.",
              score: "91.2% Reranked",
            },
            {
              id: 2,
              text: "Indonesian pro-independence fighters and militias resisted British and Indian Allied troops in fierce urban fighting.",
              score: "88.4% Reranked",
            },
          ],
        },
        "Claude Haiku 4.5": {
          precision: 0.8,
          recall: 1.0,
          f1: 0.889,
          rougeL: 0.545,
          faithfulness: 0.98,
          relevance: 0.96,
          coverage: 0.95,
          answer:
            "With MS-MARCO cross-encoder reranking, Claude Haiku 4.5 received all key ground-truth chunks. The battle was ignited by Brigadier Mallaby's death, turning into a defining moment of national independence celebrated as Heroes' Day.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "94.6% Reranked",
            },
            {
              id: 3,
              text: "The conflict resulted in heavy loss of life and became a national symbol of resistance, celebrated annually as Heroes' Day on November 10.",
              score: "91.2% Reranked",
            },
            {
              id: 2,
              text: "Indonesian pro-independence fighters and militias resisted British and Indian Allied troops in fierce urban fighting.",
              score: "88.4% Reranked",
            },
          ],
        },
      },
    },
  },
];

export const InteractiveBenchmarkSimulator: React.FC = () => {
  const [selectedMethod, setSelectedMethod] = useState<"dense" | "sparse" | "hybrid">("hybrid");
  const [selectedModel, setSelectedModel] = useState<string>("Claude Haiku 4.5");
  const [topK, setTopK] = useState<number>(5);
  const [groundTruthMode, setGroundTruthMode] = useState<"pooling" | "manual">("pooling");
  const [isSimulating, setIsSimulating] = useState<boolean>(false);

  const doc = SAMPLE_DOCS[0];
  const activeResult = doc.data[selectedMethod][selectedModel as keyof typeof doc.data.dense];

  const handleSimulateRun = () => {
    setIsSimulating(true);
    setTimeout(() => {
      setIsSimulating(false);
    }, 400);
  };

  const getMetricBadge = (score: number) => {
    const pct = Math.round(score * 100);
    if (pct >= 85) return "bg-emerald-950/80 text-emerald-400 border-emerald-800/50";
    if (pct >= 65) return "bg-cyan-950/80 text-cyan-400 border-cyan-800/50";
    return "bg-amber-950/80 text-amber-400 border-amber-800/50";
  };

  return (
    <div className="w-full bg-slate-900/90 border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl backdrop-blur-xl">
      {/* Header Controls */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6 pb-6 border-b border-slate-800">
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 text-xs font-semibold uppercase tracking-wider mb-2">
            <Sparkles className="w-3.5 h-3.5" /> Live Matrix Playground
          </div>
          <h3 className="text-2xl font-bold text-white tracking-tight">
            Benchmark Matrix Simulator
          </h3>
          <p className="text-sm text-slate-400 mt-1">
            Test how different retrieval methods and LLMs score on real document questions.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={handleSimulateRun}
            disabled={isSimulating}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-medium text-sm shadow-lg shadow-cyan-600/20 transition-all active:scale-95 disabled:opacity-50"
          >
            {isSimulating ? (
              <RotateCcw className="w-4 h-4 animate-spin" />
            ) : (
              <Zap className="w-4 h-4" />
            )}
            Run Pipeline
          </button>
        </div>
      </div>

      {/* Configuration Controls */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 my-6 p-4 rounded-2xl bg-slate-950/60 border border-slate-800/60">
        {/* Method Picker */}
        <div>
          <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Search className="w-3.5 h-3.5 text-cyan-400" /> Retrieval Method
          </label>
          <div className="grid grid-cols-3 gap-2">
            {[
              { id: "dense", label: "Dense", icon: Database },
              { id: "sparse", label: "Sparse", icon: Library },
              { id: "hybrid", label: "Hybrid", icon: Layers },
            ].map((item) => {
              const Icon = item.icon;
              const isActive = selectedMethod === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setSelectedMethod(item.id as any)}
                  className={`flex flex-col items-center justify-center p-2.5 rounded-xl border text-xs font-medium transition-all ${
                    isActive
                      ? "bg-cyan-500/15 border-cyan-500/50 text-cyan-300 shadow-md shadow-cyan-500/10"
                      : "bg-slate-900/50 border-slate-800 text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
                  }`}
                >
                  <Icon className="w-4 h-4 mb-1" />
                  {item.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Model Picker */}
        <div>
          <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Bot className="w-3.5 h-3.5 text-cyan-400" /> LLM Generator
          </label>
          <div className="grid grid-cols-3 gap-2">
            {["GPT-4o mini", "Gemini 3 Flash", "Claude Haiku 4.5"].map((model) => {
              const isActive = selectedModel === model;
              return (
                <button
                  key={model}
                  onClick={() => setSelectedModel(model)}
                  className={`p-2.5 rounded-xl border text-xs font-medium text-center transition-all ${
                    isActive
                      ? "bg-blue-500/15 border-blue-500/50 text-blue-300 shadow-md shadow-blue-500/10"
                      : "bg-slate-900/50 border-slate-800 text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
                  }`}
                >
                  {model}
                </button>
              );
            })}
          </div>
        </div>

        {/* Top-K & Ground Truth Mode */}
        <div className="flex flex-col justify-between gap-2">
          <div>
            <div className="flex justify-between items-center text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
              <span className="flex items-center gap-1.5">
                <Sliders className="w-3.5 h-3.5 text-cyan-400" /> Depth Top-K
              </span>
              <span className="text-cyan-400 font-mono font-bold">{topK}</span>
            </div>
            <input
              type="range"
              min={1}
              max={15}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
              className="w-full accent-cyan-400 bg-slate-800 rounded-lg h-2 cursor-pointer"
            />
          </div>

          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-400 font-medium">Ground Truth Mode:</span>
            <div className="inline-flex rounded-lg p-0.5 bg-slate-900 border border-slate-800">
              <button
                onClick={() => setGroundTruthMode("pooling")}
                className={`px-2 py-1 rounded-md text-[11px] font-medium transition-all ${
                  groundTruthMode === "pooling"
                    ? "bg-cyan-500/20 text-cyan-300 font-semibold"
                    : "text-slate-500 hover:text-slate-300"
                }`}
              >
                RRF Pooling
              </button>
              <button
                onClick={() => setGroundTruthMode("manual")}
                className={`px-2 py-1 rounded-md text-[11px] font-medium transition-all ${
                  groundTruthMode === "manual"
                    ? "bg-cyan-500/20 text-cyan-300 font-semibold"
                    : "text-slate-500 hover:text-slate-300"
                }`}
              >
                Manual Ticks
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Main Results Showcase */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Query & Answer */}
        <div className="lg:col-span-7 space-y-4">
          {/* Query Box */}
          <div className="p-4 rounded-xl bg-slate-950/80 border border-slate-800">
            <div className="flex items-center justify-between text-xs text-slate-500 mb-1.5 uppercase font-mono tracking-wider">
              <span className="flex items-center gap-1.5">
                <FileText className="w-3.5 h-3.5 text-slate-400" /> Query
              </span>
              <span>Top-K: {topK}</span>
            </div>
            <p className="text-sm font-semibold text-white">{doc.defaultQuery}</p>
          </div>

          {/* Generated Answer Box */}
          <div className="p-5 rounded-2xl bg-slate-950/90 border border-cyan-500/20 relative overflow-hidden group">
            <div className="absolute top-0 right-0 w-32 h-32 bg-cyan-500/5 rounded-full blur-2xl pointer-events-none" />
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider flex items-center gap-1.5">
                <Bot className="w-4 h-4" /> Generated Answer — {selectedModel}
              </span>
              <span className="text-[11px] px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-300 font-mono">
                {selectedMethod.toUpperCase()}
              </span>
            </div>
            <p className="text-sm text-slate-200 leading-relaxed font-normal">
              {activeResult.answer}
            </p>
          </div>

          {/* Retrieved Chunks Preview */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-slate-400 font-semibold uppercase tracking-wider">
              <span>Retrieved Chunks ({activeResult.chunks.length})</span>
              <span>Retrieval Score</span>
            </div>
            {activeResult.chunks.map((chunk) => (
              <div
                key={chunk.id}
                className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 flex items-start justify-between gap-3 text-xs"
              >
                <div className="flex items-start gap-2">
                  <span className="px-1.5 py-0.5 rounded bg-slate-800 text-cyan-400 font-mono text-[10px]">
                    #{chunk.id}
                  </span>
                  <p className="text-slate-300 leading-normal">{chunk.text}</p>
                </div>
                <span className="shrink-0 px-2 py-0.5 rounded-full bg-emerald-950/60 border border-emerald-800/40 text-emerald-400 font-mono font-medium text-[11px]">
                  {chunk.score}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Right Column: 9-Metric Matrix Dashboard */}
        <div className="lg:col-span-5 space-y-4">
          <div className="p-5 rounded-2xl bg-slate-950/90 border border-slate-800">
            <div className="flex items-center justify-between mb-4 border-b border-slate-800 pb-3">
              <span className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                <BarChart3 className="w-4 h-4 text-cyan-400" /> Score Matrix (9 Metrics)
              </span>
              <span className="text-[11px] text-slate-500 font-mono">Normalized 0-100%</span>
            </div>

            {/* Chunk Retrieval Metrics */}
            <div className="mb-4">
              <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-2">
                Retrieval Set Overlap
              </span>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: "Precision@K", val: activeResult.precision },
                  { label: "Recall@K", val: activeResult.recall },
                  { label: "F1@K", val: activeResult.f1 },
                ].map((m) => (
                  <div
                    key={m.label}
                    className={`p-2.5 rounded-xl border text-center ${getMetricBadge(m.val)}`}
                  >
                    <span className="block text-[10px] text-slate-400 mb-0.5">{m.label}</span>
                    <span className="text-base font-bold font-mono">
                      {Math.round(m.val * 100)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Answer Generation Metrics */}
            <div>
              <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-2">
                Answer Quality & LLM Judge
              </span>
              <div className="grid grid-cols-2 gap-2">
                {[
                  { label: "ROUGE-L F1", val: activeResult.rougeL },
                  { label: "Faithfulness", val: activeResult.faithfulness },
                  { label: "Answer Relevance", val: activeResult.relevance },
                  { label: "Answer Coverage", val: activeResult.coverage },
                ].map((m) => (
                  <div
                    key={m.label}
                    className={`p-2.5 rounded-xl border text-center ${getMetricBadge(m.val)}`}
                  >
                    <span className="block text-[10px] text-slate-400 mb-0.5">{m.label}</span>
                    <span className="text-base font-bold font-mono">
                      {Math.round(m.val * 100)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center gap-2 text-xs text-slate-400">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>
                {selectedMethod === "hybrid"
                  ? "Hybrid + Cross-encoder reranker achieved highest recall & faithfulness."
                  : "Try switching to Hybrid to see cross-encoder reranking boost scores."}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default InteractiveBenchmarkSimulator;
