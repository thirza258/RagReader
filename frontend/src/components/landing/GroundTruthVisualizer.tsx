import React, { useState } from "react";

const SAMPLE_CHUNKS = [
  {
    id: "chunk_102",
    text: "The Battle of Surabaya occurred in November 1945 following Brigadier A. W. S. Mallaby's death.",
    rrfScore: "0.04918",
    status: "Ground truth #1",
    foundBy: ["Dense", "Sparse", "Hybrid"],
    included: true,
  },
  {
    id: "chunk_105",
    text: "Indonesian pro-independence militias fiercely resisted British and Indian Allied military forces.",
    rrfScore: "0.04838",
    status: "Ground truth #2",
    foundBy: ["Dense", "Sparse", "Hybrid"],
    included: true,
  },
  {
    id: "chunk_109",
    text: "The heavy battle casualties turned Surabaya into a national symbol, celebrated as Heroes' Day on 10 November.",
    rrfScore: "0.04791",
    status: "Ground truth #3",
    foundBy: ["Dense", "Sparse", "Hybrid"],
    included: true,
  },
  {
    id: "chunk_118",
    text: "Surabaya was a major industrial centre in East Java with strategic port facilities during the Second World War.",
    rrfScore: "0.04364",
    status: "Excluded (rank > K)",
    foundBy: ["Sparse"],
    included: false,
  },
];

type Mode = "pooling" | "manual";

export const GroundTruthVisualizer: React.FC = () => {
  const [mode, setMode] = useState<Mode>("pooling");
  const [poolDepth, setPoolDepth] = useState(10);

  const tab = (value: Mode, label: string) => (
    <button
      key={value}
      onClick={() => setMode(value)}
      aria-pressed={mode === value}
      className={`border-b-2 px-1 pb-2 text-sm transition-colors ${
        mode === value
          ? "border-primary font-medium text-foreground"
          : "border-transparent text-muted-foreground hover:text-foreground"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div>
      <div className="flex gap-6 border-b border-border">
        {tab("pooling", "Candidate pooling (RRF)")}
        {tab("manual", "Manual selection")}
      </div>

      <div className="mt-8 grid gap-10 lg:grid-cols-[22rem_1fr]">
        <div>
          {mode === "pooling" ? (
            <>
              <p className="prose-note text-base">
                Candidate pooling queries dense, sparse and hybrid retrieval in
                parallel, then merges the three rankings so chunks that several
                independent engines agree on rise to the top.
              </p>

              <div className="mt-5 border border-border px-4 py-3 text-center font-mono text-sm">
                RRF(c) = Σ<sub>m</sub> 1 / (60 + rank<sub>m</sub>(c))
              </div>

              <div className="mt-6">
                <label
                  htmlFor="pool-depth"
                  className="flex items-baseline justify-between text-sm"
                >
                  <span className="text-muted-foreground">Pool depth (default 10)</span>
                  <span className="font-mono tabular">{poolDepth}</span>
                </label>
                <input
                  id="pool-depth"
                  type="range"
                  min={5}
                  max={20}
                  value={poolDepth}
                  onChange={(event) => setPoolDepth(Number(event.target.value))}
                  className="mt-2 h-1 w-full cursor-pointer appearance-none bg-border accent-primary"
                />
              </div>
            </>
          ) : (
            <>
              <p className="prose-note text-base">
                Inspect the document chunk by chunk and tick the ones that contain the
                answer. Slower, and it is your judgement being measured — but no
                retriever gets a say in defining its own target.
              </p>
              <ul className="mt-5 space-y-2 text-sm text-muted-foreground">
                <li>— Removes algorithmic bias from the reference set.</li>
                <li>— Lets a domain expert set a stricter bar for relevance.</li>
              </ul>
            </>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[30rem] border-t border-border text-sm">
            <caption className="caption-bottom pt-3 text-left text-sm text-muted-foreground">
              Table 2. Fused candidate ranking for a sample query. Rows below the pool
              cut-off are excluded from the ground-truth set.
            </caption>
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th scope="col" className="py-2 pr-4 font-medium">Chunk</th>
                <th scope="col" className="py-2 pr-4 font-medium">Retrieved by</th>
                <th scope="col" className="py-2 text-right font-medium">RRF</th>
              </tr>
            </thead>
            <tbody>
              {SAMPLE_CHUNKS.map((chunk) => (
                <tr
                  key={chunk.id}
                  className={`border-b border-border align-top ${
                    chunk.included ? "" : "text-muted-foreground"
                  }`}
                >
                  <td className="py-3 pr-4">
                    <span className="font-mono text-xs">{chunk.id}</span>
                    <span className="ml-2 text-xs text-muted-foreground">
                      {chunk.status}
                    </span>
                    <p className="mt-1 max-w-md text-muted-foreground">{chunk.text}</p>
                  </td>
                  <td className="py-3 pr-4 text-xs text-muted-foreground">
                    {chunk.foundBy.join(", ")}
                  </td>
                  <td className="py-3 text-right font-mono text-xs tabular">
                    {chunk.rrfScore}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default GroundTruthVisualizer;
