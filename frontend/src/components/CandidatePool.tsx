import React, { useState } from "react";
import { AlertCircle, FileText, Layers, Loader2, RefreshCw, Sparkles } from "lucide-react";
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
  <div className="rounded-lg border border-border bg-card p-4">
    <div className="flex items-start justify-between gap-3 mb-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">
          {chunk.rank}
        </span>
        <FileText size={12} />
        <span className="truncate max-w-[120px]">{chunk.chunk_id}</span>
      </div>
      <span className="shrink-0 rounded bg-muted px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
        RRF {chunk.rrf_score.toFixed(4)}
      </span>
    </div>

    <p className="text-sm leading-relaxed text-foreground/90 line-clamp-4">{chunk.text}</p>

    <div className="mt-3 flex flex-wrap gap-1.5">
      {chunk.sources.map((source) => (
        <span
          key={source.pipeline}
          title={`${source.pipeline} ranked this #${source.rank}`}
          className="rounded-full border border-border bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground"
        >
          {source.pipeline.replace(" Retrieval", "")} #{source.rank}
        </span>
      ))}
    </div>
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
      <div className="rounded-lg border border-border bg-muted/20 p-4">
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
          "flex items-center justify-center gap-2 rounded-md border border-border px-4 py-2.5 text-sm font-medium transition-colors",
          isPooling
            ? "cursor-not-allowed bg-muted text-muted-foreground"
            : "bg-primary text-primary-foreground hover:opacity-90"
        )}
      >
        {isPooling ? (
          <>
            <Loader2 size={16} className="animate-spin" />
            Retrieving from every method…
          </>
        ) : (
          <>
            {pool ? <RefreshCw size={16} /> : <Sparkles size={16} />}
            {pool ? `Re-run pooling (top ${poolTopN})` : `Run candidate pooling (top ${poolTopN})`}
          </>
        )}
      </button>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {pool && (
        <>
          <div className="flex flex-wrap items-center gap-3 border-b border-border/40 pb-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5 font-medium text-foreground">
              <Layers size={14} />
              {pool.chunks.length} pooled chunks
            </span>
            <span>RRF k = {pool.rrf_k}</span>
            {pool.pipelines.map((pipeline) => (
              <span
                key={pipeline.name}
                className={cn(
                  "rounded-full px-2 py-0.5",
                  pipeline.error
                    ? "bg-destructive/10 text-destructive"
                    : "bg-muted text-muted-foreground"
                )}
                title={pipeline.error ?? undefined}
              >
                {pipeline.name.replace(" Retrieval", "")}: {pipeline.error ? "failed" : pipeline.retrieved}
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
