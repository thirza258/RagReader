import type { RetrievalMetadata } from "../types/index.ts";

/** "2.6 s" for 2600 ms; "120 ms" below a second when asked for. */
export function formatDuration(ms: number | null | undefined, options: { precise?: boolean } = {}): string | null {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return null;
  if (options.precise && ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatScore(score: number | null | undefined): string | null {
  if (score == null || !Number.isFinite(score)) return null;
  return score.toFixed(2);
}

/**
 * The workspace footer (PRD §37):
 * "Retrieval: 20 → 5 → 3 cited · 2.6 s · first token 0.9 s".
 * Parts the metadata does not have are left out; null when nothing is known.
 */
export function formatRetrievalSummary(
  retrieval: RetrievalMetadata | null | undefined,
  latencyMs?: number | null,
): string | null {
  if (!retrieval) return null;
  const parts: string[] = [];
  const counts: string[] = [];
  if (retrieval.candidate_count != null) counts.push(String(retrieval.candidate_count));
  if (retrieval.context_count != null) counts.push(String(retrieval.context_count));
  if (retrieval.cited_count != null) counts.push(`${retrieval.cited_count} cited`);
  if (counts.length > 0) parts.push(`Retrieval: ${counts.join(" → ")}`);
  const total = formatDuration(retrieval.timings_ms?.total ?? latencyMs ?? null);
  if (total) parts.push(total);
  const firstToken = formatDuration(retrieval.timings_ms?.first_token ?? null);
  if (firstToken) parts.push(`first token ${firstToken}`);
  return parts.length > 0 ? parts.join(" · ") : null;
}
