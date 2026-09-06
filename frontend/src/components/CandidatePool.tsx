import React, { useState } from "react";
import { Loader2 } from "lucide-react";
import service from "../services/service";
import { CandidatePoolResponse, PooledChunk } from "../interface";

const cn = (...classes: (string | undefined | boolean)[]) =>
  classes.filter(Boolean).join(" ");

interface CandidatePoolProps {
  conversationId: string;
  poolTopN: number;
  pool: CandidatePoolResponse | null;
  onPooled: (pool: CandidatePoolResponse | null) => void;
}

/** Reads the server error out of an axios-shaped rejection. */
function describeError(error: unknown): string {
  const response = (error as { response?: { status?: number; data?: { error?: string } } })
    ?.response;
  if (response?.status === 503) {
    return "The retrieval engines aren't loaded yet. Upload a document and let indexing finish, then try again.";
  }
  return (
    response?.data?.error ??
    "Candidate pooling failed. Your existing ground truth was left unchanged."
  );
}

const PooledChunkCard: React.FC<{ chunk: PooledChunk }> = ({ chunk }) => (
  <div className="border border-border p-4">
    <div className="mb-2 flex items-baseline justify-between gap-3">
      <span className="flex items-baseline gap-2 font-mono text-xs text-muted-foreground">
        <span className="text-foreground tabular">{chunk.rank}.</span>
        <span className="max-w-[140px] truncate">{chunk.chunk_id}</span>
      </span>
      <span className="shrink-0 font-mono text-xs text-muted-foreground tabular">
        RRF {chunk.rrf_score.toFixed(4)}
      </span>
    </div>

    <p className="line-clamp-4 text-sm leading-relaxed text-muted-foreground">
      {chunk.text}
    </p>

    <p className="mt-3 text-xs text-muted-foreground">
      {chunk.sources
        .map((source) => `${source.pipeline.replace(" Retrieval", "")} #${source.rank}`)
        .join(" · ")}
    </p>
  </div>
);

/**
 * Runs candidate pooling for a conversation and previews the fused ranking.
 * Pooling writes the ground truth server-side, so a successful run here is
 * all the "Step 1" the analysis needs.
 */
const CandidatePool: React.FC<CandidatePoolProps> = ({
  conversationId,
  poolTopN,
  pool,
  onPooled,
}) => {
  const [isPooling, setIsPooling] = useState(false);
  const [error, setError] = useState("");

  const runPooling = async () => {
    setIsPooling(true);
    setError("");
    try {
      const result = await service.poolGroundTruthChunks(conversationId, {
        top_n: poolTopN,
      });
      onPooled(result);
    } catch (err) {
      console.error("Candidate pooling failed:", err);
      setError(describeError(err));
      onPooled(null);
    } finally {
      setIsPooling(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="border-l-2 border-border py-1 pl-4">
        <p className="text-sm text-muted-foreground">
          Runs your question through <strong>Dense</strong>, <strong>Sparse</strong> and{" "}
          <strong>Hybrid</strong> retrieval, then fuses the three rankings with Reciprocal
          Rank Fusion. Chunks that several retrievers agree on rise to the top, so no
          single method defines what counts as relevant.
        </p>
        <p className="mt-2 text-xs text-muted-foreground">
          Pooling <em>replaces</em> the ground truth for this conversation, including any
          chunks you picked by hand.
        </p>
      </div>

      <button
        onClick={runPooling}
        disabled={isPooling}
        className={cn(
          "flex items-center justify-center gap-2 border px-4 py-2.5 text-sm font-medium transition-colors",
          isPooling
            ? "cursor-not-allowed border-border text-muted-foreground"
            : "border-primary bg-primary text-primary-foreground hover:bg-primary-hover"
        )}
      >
        {isPooling && <Loader2 size={15} className="animate-spin" />}
        {isPooling
          ? "Retrieving from every method…"
          : pool
            ? `Re-run pooling (top ${poolTopN})`
            : `Run candidate pooling (top ${poolTopN})`}
      </button>

      {error && (
        <div className="border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {pool && (
        <>
          <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 border-b border-border pb-3 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">
              {pool.chunks.length} pooled chunks
            </span>
            <span className="font-mono">RRF k = {pool.rrf_k}</span>
            {pool.pipelines.map((pipeline) => (
              <span
                key={pipeline.name}
                className={cn("font-mono", pipeline.error ? "text-destructive" : "")}
                title={pipeline.error ?? undefined}
              >
                {pipeline.name.replace(" Retrieval", "")}:{" "}
                {pipeline.error ? "failed" : pipeline.retrieved}
              </span>
            ))}
          </div>

          {pool.optimized_query && pool.optimized_query !== pool.query && (
            <p className="text-xs text-muted-foreground">
              Retrieved with the rewritten query:{" "}
              <span className="italic text-foreground/80">"{pool.optimized_query}"</span>
            </p>
          )}

          <div className="custom-scrollbar grid max-h-[500px] grid-cols-1 gap-4 overflow-y-auto pr-2 lg:grid-cols-2">
            {pool.chunks.map((chunk) => (
              <PooledChunkCard key={chunk.chunk_id} chunk={chunk} />
            ))}
          </div>
        </>
      )}
    </div>
  );
};

export default CandidatePool;
