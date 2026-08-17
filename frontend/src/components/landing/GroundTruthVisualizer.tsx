import React, { useState } from "react";
import { GitBranch, ListChecks, Check, Sparkles } from "lucide-react";

export const GroundTruthVisualizer: React.FC = () => {
  const [activeTab, setActiveTab] = useState<"pooling" | "manual">("pooling");
  const [poolDepth, setPoolDepth] = useState<number>(10);

  const sampleChunks = [
    {
      id: "chunk_102",
      text: "The Battle of Surabaya occurred in November 1945 following Brigadier A. W. S. Mallaby's death.",
      denseRank: 1,
      sparseRank: 1,
      hybridRank: 1,
      rrfScore: "0.04918",
      status: "Ground Truth #1",
      foundBy: ["Dense", "Sparse", "Hybrid"],
    },
    {
      id: "chunk_105",
      text: "Indonesian pro-independence militias fiercely resisted British and Indian Allied military forces.",
      denseRank: 2,
      sparseRank: 3,
      hybridRank: 2,
      rrfScore: "0.04838",
      status: "Ground Truth #2",
      foundBy: ["Dense", "Sparse", "Hybrid"],
    },
    {
      id: "chunk_109",
      text: "The heavy battle casualties turned Surabaya into a national symbol, celebrated as Heroes' Day on Nov 10.",
      denseRank: 4,
      sparseRank: 2,
      hybridRank: 3,
      rrfScore: "0.04791",
      status: "Ground Truth #3",
      foundBy: ["Dense", "Sparse", "Hybrid"],
    },
    {
      id: "chunk_118",
      text: "Surabaya was a major industrial center in East Java with strategic port facilities during WWII.",
      denseRank: 12,
      sparseRank: 4,
      hybridRank: 11,
      rrfScore: "0.04364",
      status: "Excluded (Rank > K)",
      foundBy: ["Sparse"],
    },
  ];

  return (
    <div className="w-full bg-slate-900/80 border border-slate-800 rounded-3xl p-6 sm:p-8 backdrop-blur-xl">
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6 pb-6 border-b border-slate-800">
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 text-xs font-semibold uppercase tracking-wider mb-2">
            <Sparkles className="w-3.5 h-3.5" /> Objective Benchmark Standard
          </div>
          <h3 className="text-2xl font-bold text-white tracking-tight">
            Ground Truth & Consensus Candidate Pooling
          </h3>
          <p className="text-sm text-slate-400 mt-1">
            Ground truth determines the baseline against which Precision@K and Recall@K are calculated.
          </p>
        </div>

        {/* Tab Switcher */}
        <div className="inline-flex rounded-xl p-1 bg-slate-950 border border-slate-800">
          <button
            onClick={() => setActiveTab("pooling")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
              activeTab === "pooling"
                ? "bg-purple-600 text-white shadow-md shadow-purple-600/20"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <GitBranch className="w-3.5 h-3.5" /> Candidate Pooling (RRF)
          </button>
          <button
            onClick={() => setActiveTab("manual")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
              activeTab === "manual"
                ? "bg-purple-600 text-white shadow-md shadow-purple-600/20"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <ListChecks className="w-3.5 h-3.5" /> Manual Selection
          </button>
        </div>
      </div>

      {/* Content Area */}
      <div className="mt-6 grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        {/* Explanation & Math Formula */}
        <div className="lg:col-span-5 space-y-4">
          {activeTab === "pooling" ? (
            <>
              <div className="p-5 rounded-2xl bg-purple-950/20 border border-purple-500/20 space-y-3">
                <h4 className="text-base font-bold text-purple-200 flex items-center gap-2">
                  <GitBranch className="w-4 h-4 text-purple-400" /> Reciprocal Rank Fusion (RRF)
                </h4>
                <p className="text-xs text-slate-300 leading-relaxed">
                  Candidate pooling queries Dense, Sparse, and Hybrid retrievers in parallel. The rankings are combined mathematically so chunks agreed upon by multiple independent search engines rise to the top.
                </p>
                <div className="p-3 rounded-xl bg-slate-950 border border-purple-500/30 text-center font-mono text-xs text-purple-300">
                  RRF Score = &Sigma; 1 / (60 + rank<sub>m</sub>)
                </div>
              </div>

              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400 font-medium">Pool Depth Limit (Default: 10):</span>
                  <span className="font-mono text-purple-400 font-bold">{poolDepth} chunks</span>
                </div>
                <input
                  type="range"
                  min={5}
                  max={20}
                  value={poolDepth}
                  onChange={(e) => setPoolDepth(Number(e.target.value))}
                  className="w-full accent-purple-500 bg-slate-800 rounded-lg h-2 cursor-pointer"
                />
              </div>
            </>
          ) : (
            <div className="p-5 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-3">
              <h4 className="text-base font-bold text-white flex items-center gap-2">
                <ListChecks className="w-4 h-4 text-cyan-400" /> Manual Chunk Ticking
              </h4>
              <p className="text-xs text-slate-300 leading-relaxed">
                Inspect document chunks line by line and explicitly tick which chunks contain the exact answer to your question.
              </p>
              <ul className="space-y-2 text-xs text-slate-400">
                <li className="flex items-center gap-2">
                  <Check className="w-3.5 h-3.5 text-emerald-400" /> Eliminates algorithmic bias in benchmark reference sets.
                </li>
                <li className="flex items-center gap-2">
                  <Check className="w-3.5 h-3.5 text-emerald-400" /> Allows human experts to specify strict domain precision.
                </li>
              </ul>
            </div>
          )}
        </div>

        {/* Live Ranking Table */}
        <div className="lg:col-span-7 space-y-3">
          <div className="flex items-center justify-between text-xs text-slate-400 font-semibold uppercase tracking-wider px-2">
            <span>Fused Candidate Ranking</span>
            <span>RRF Score</span>
          </div>

          {sampleChunks.map((chunk, idx) => (
            <div
              key={chunk.id}
              className={`p-4 rounded-xl border transition-all ${
                idx < 3
                  ? "bg-slate-950/80 border-purple-500/30 shadow-md shadow-purple-950/20"
                  : "bg-slate-950/40 border-slate-800/60 opacity-60"
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded bg-purple-950 text-purple-300 font-mono text-xs font-bold border border-purple-800/40">
                    {chunk.id}
                  </span>
                  <span className="text-xs font-semibold text-white">{chunk.status}</span>
                </div>
                <span className="font-mono text-xs text-purple-400 font-bold">{chunk.rrfScore}</span>
              </div>
              <p className="text-xs text-slate-300 leading-relaxed mb-3">{chunk.text}</p>
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-slate-500 uppercase font-mono">Found By:</span>
                {chunk.foundBy.map((f) => (
                  <span
                    key={f}
                    className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-medium"
                  >
                    {f}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default GroundTruthVisualizer;
