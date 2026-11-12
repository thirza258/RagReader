import type { ChatMessage, Evidence, RetrievalMetadata } from "../../chat/types/index.ts";
import type { PercentileStat, ReliabilitySummary, RetrievalRun, RunCandidate, RunQuery } from "../types/index.ts";

/**
 * Formatting and derivations for retrieval runs: latencies, percentiles,
 * rates, the retrieval funnel, the rewrite explanation and the reliability
 * summary cards. Pure, so the Why panel and the Runs view agree and tests can
 * pin the wording.
 */

const DASH = "—";

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** "<1 ms", "120 ms", "2.45 s", "12.3 s"; "—" when unknown. */
export function formatMs(ms: number | null | undefined): string {
  if (!isNumber(ms) || ms < 0) return DASH;
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}

/** "p50 2.40 s · p95 5.10 s"; "—" when there is no sample. */
export function formatPercentiles(stat: PercentileStat | null | undefined): string {
  if (!stat || stat.count === 0 || (stat.p50 == null && stat.p95 == null)) return DASH;
  return `p50 ${formatMs(stat.p50)} · p95 ${formatMs(stat.p95)}`;
}

/** 0.375 → "37.5%", 0 → "0%", null → "—". */
export function formatRate(rate: number | null | undefined): string {
  if (!isNumber(rate)) return DASH;
  const percent = Math.round(rate * 1000) / 10;
  return `${percent.toFixed(1).replace(/\.0$/, "")}%`;
}

export function formatCount(value: number | null | undefined): string {
  return isNumber(value) ? Math.round(value).toLocaleString("en-US") : DASH;
}

export interface FunnelStep {
  key: "candidates" | "context" | "cited";
  label: string;
  value: number | null;
}

/** Retrieved candidates → context → cited, from a run or Phase 1 metadata. */
export function runFunnel(source: Pick<RetrievalRun, "candidate_count" | "context_count" | "cited_count"> | RetrievalMetadata | null | undefined): FunnelStep[] {
  const pick = (value: unknown) => (isNumber(value) ? value : null);
  return [
    { key: "candidates", label: "Retrieved candidates", value: pick(source?.candidate_count) },
    { key: "context", label: "Context", value: pick(source?.context_count) },
    { key: "cited", label: "Cited", value: pick(source?.cited_count) },
  ];
}

/** "Retrieved candidates 20 → Context 5 → Cited 3". */
export function funnelText(steps: readonly FunnelStep[]): string {
  return steps.map((step) => `${step.label} ${step.value == null ? DASH : step.value.toLocaleString("en-US")}`).join(" → ");
}

/** "20 → 5 → 3" for list rows. */
export function funnelShort(steps: readonly FunnelStep[]): string {
  return steps.map((step) => (step.value == null ? DASH : String(step.value))).join(" → ");
}

const NOT_REWRITTEN: Record<string, string> = {
  first_question: "first question in the conversation, so there was nothing to resolve",
  unchanged: "the rewrite came back identical to the question",
  unusable: "the rewrite was unusable (empty, several lines or over 200 characters)",
  failed: "the rewrite request failed",
};

/** How the question was searched: the rewrite, or why there was none. */
export function describeRewrite(query: Partial<RunQuery> | null | undefined): { applied: boolean; text: string } {
  if (query?.rewrite_applied && query.rewritten) return { applied: true, text: query.rewritten };
  const reason = query?.rewrite_reason ? NOT_REWRITTEN[query.rewrite_reason] : null;
  return { applied: false, text: reason ? `Not rewritten: ${reason}.` : "Not rewritten." };
}

const STAGES: Record<string, string> = { rewrite: "query rewrite", retrieve: "retrieval", generate: "generation" };

/** "retrieval" for "retrieve"; unknown stages are shown as given. */
export function stageName(stage: string | null | undefined): string {
  if (!stage) return "an unknown step";
  return STAGES[stage] ?? stage;
}

export interface SummaryCard {
  key: string;
  label: string;
  value: string;
  detail: string;
}

/** The Runs view header (PRD §49). */
export function summaryCards(summary: ReliabilitySummary | null | undefined): SummaryCard[] {
  if (!summary) return [];
  const { runs, failures_by_stage: stages, latency_ms: latency, tokens, ingestion } = summary;
  return [
    { key: "runs", label: "Runs", value: formatCount(runs.total), detail: `${formatCount(runs.completed)} completed · ${formatCount(runs.failed)} failed` },
    {
      key: "failures",
      label: "Failure rate",
      value: formatRate(summary.failure_rate),
      detail: `retrieval ${formatRate(stages.retrieval.rate)} · generation ${formatRate(stages.generation.rate)}`,
    },
    { key: "total", label: "Total latency", value: formatPercentiles(latency.total), detail: `${formatCount(latency.total.count)} completed runs` },
    { key: "first_token", label: "First token", value: formatPercentiles(latency.first_token), detail: "from question to first token" },
    { key: "retrieval", label: "Retrieval", value: formatPercentiles(latency.retrieval), detail: "load indexes, embed, search, select" },
    { key: "generation", label: "Generation", value: formatPercentiles(latency.generation), detail: "request to last token" },
    {
      key: "tokens",
      label: "Tokens per answer",
      value: tokens.average_per_run == null ? DASH : formatCount(tokens.average_per_run),
      detail: `${formatCount(tokens.total)} in total`,
    },
    {
      key: "ingestion",
      label: "Ingestion success",
      value: formatRate(ingestion.success_rate),
      detail: `${formatCount(ingestion.ready)} ready · ${formatCount(ingestion.failed)} failed${ingestion.in_progress ? ` · ${formatCount(ingestion.in_progress)} in progress` : ""}`,
    },
  ];
}

/** A candidate as reader evidence; null when its document is gone. */
export function candidateToEvidence(candidate: RunCandidate): Evidence | null {
  if (candidate.document_id == null || !candidate.document_available) return null;
  return {
    citation_id: candidate.citation_id ?? 0,
    candidate_rank: candidate.rank,
    document_id: candidate.document_id,
    document_title: candidate.document_title,
    index_version_id: candidate.index_version_id,
    chunk_id: candidate.chunk_id,
    page_number: candidate.page_number,
    page_end: candidate.page_end,
    char_start: candidate.char_start,
    char_end: candidate.char_end,
    text: candidate.text,
    retrieval_score: candidate.retrieval_score,
    rerank_score: candidate.rerank_score,
    cited: candidate.cited,
  };
}

/** The run behind an answer, when the server recorded one. */
export function runIdOf(message: Pick<ChatMessage, "retrieval"> | null | undefined): number | null {
  const id = message?.retrieval?.run_id;
  return typeof id === "number" && Number.isInteger(id) && id > 0 ? id : null;
}

/** "2.45 s · first token 0.90 s · 908 tokens · 20 → 5 → 3" for a run row. */
export function runLine(run: RetrievalRun): string {
  const parts = [formatMs(run.latency_ms?.total)];
  if (run.latency_ms?.first_token != null) parts.push(`first token ${formatMs(run.latency_ms.first_token)}`);
  if (run.token_usage?.total_tokens != null) parts.push(`${formatCount(run.token_usage.total_tokens)} tokens`);
  parts.push(funnelShort(runFunnel(run)));
  return parts.join(" · ");
}
