/** Shapes of the retrieval-run endpoints (docs/prd-implementation.md, Phase 2). */
import type { TokenUsage } from "../../chat/types/index.ts";
import type { PipelineConfig } from "../../pipelines/types/index.ts";

export type RunStatus = "completed" | "failed";
export type RunSource = "chat" | "evaluation" | "research";
/** `fallback`: the step failed but the request went on with a fallback (Phase 3: reranking kept the fused order). */
export type SpanStatus = "completed" | "skipped" | "failed" | "fallback";

/** One step of a run's trace; offsets are milliseconds from the run's start. */
export interface RunSpan {
  name: string;
  label: string;
  status: SpanStatus;
  start_ms: number;
  duration_ms: number | null;
  detail: string;
  error_code: string | null;
  data: Record<string, unknown>;
  children: RunSpan[];
}

export interface RunCandidate {
  rank: number;
  document_id: number | null;
  document_title: string;
  /** False once the document has been deleted; title and text are kept. */
  document_available: boolean;
  index_version_id: number | null;
  chunk_id: number | null;
  page_number: number | null;
  page_end: number | null;
  char_start: number | null;
  char_end: number | null;
  text: string;
  /** The score it was retrieved by: cosine (dense), BM25 (bm25) or fused (hybrid strategies). */
  retrieval_score: number | null;
  rerank_score: number | null;
  /** Phase 3: score components (null when the strategy did not compute one). */
  dense_score?: number | null;
  bm25_score?: number | null;
  fused_score?: number | null;
  /** Phase 3: rank before reranking; `rank` is the final one. Null on runs from before Phase 3. */
  retrieval_rank?: number | null;
  selected_for_context: boolean;
  cited: boolean;
  /** The `[n]` the passage had in the prompt; null when it was not in the context. */
  citation_id: number | null;
}

/** Phase 3: the reranker in a run's provenance. */
export interface RerankerProvenance {
  provider: string | null;
  model: string | null;
  applied: boolean;
  fallback: boolean;
  error_code: string | null;
}

/** Phase 3: the pipeline version in a run's provenance (kept after the pipeline is deleted). */
export interface PipelineProvenance {
  pipeline_id: number | null;
  name: string | null;
  version_id: number | null;
  version: number | null;
  config: PipelineConfig | null;
  config_hash: string | null;
}

export interface IndexVersion {
  document_id: number;
  document_title: string;
  index_version_id: number | null;
  method: string | null;
  created_at: string | null;
  embedding_model: string | null;
  loaded: boolean;
}

/** PRD §20: what produced the answer. */
export interface RunProvenance {
  schema_version?: number;
  timestamp?: string;
  strategy?: string;
  retrieval_parameters?: Record<string, unknown>;
  embedding_model?: string | null;
  /** Null without a reranker (and on runs from before Phase 3). */
  reranker?: RerankerProvenance | string | null;
  generation_model?: string | null;
  configured_generation_model?: string | null;
  fallback_used?: boolean;
  generation_parameters?: Record<string, unknown>;
  prompt_version?: string | null;
  index_versions?: IndexVersion[];
  index_version_count?: number;
  pipeline?: PipelineProvenance | null;
}

export interface RunQuery {
  original: string;
  rewritten: string;
  rewrite_applied: boolean;
  /** first_question, rewritten, unchanged, unusable or failed. */
  rewrite_reason: string | null;
}

export interface RunError {
  code: string;
  message: string;
  /** rewrite, retrieve or generate. */
  stage: string | null;
}

export interface RunLatency {
  total: number | null;
  rewrite: number | null;
  retrieval: number | null;
  rerank: number | null;
  generation: number | null;
  first_token: number | null;
}

/** A run as listed. */
export interface RetrievalRun {
  id: number;
  workspace_id: number;
  conversation_id: number | null;
  message_id: number | null;
  source: RunSource | string;
  status: RunStatus;
  query: RunQuery;
  error: RunError | null;
  latency_ms: RunLatency;
  token_usage: TokenUsage | null;
  candidate_count: number;
  context_count: number;
  cited_count: number;
  strategy: string | null;
  generation_model: string | null;
  /** Phase 3: null before pipelines and after the pipeline was deleted. */
  pipeline_version_id?: number | null;
  pipeline?: { id: number | null; name: string | null; version: number | null; version_id: number | null } | null;
  started_at: string;
  created_at: string;
}

/** A run with its full trace. */
export interface RetrievalRunDetail extends RetrievalRun {
  provenance: RunProvenance;
  spans: RunSpan[];
  candidates: RunCandidate[];
}

export interface RunList {
  results: RetrievalRun[];
  has_more: boolean;
}

export interface PercentileStat {
  p50: number | null;
  p95: number | null;
  count: number;
}

export interface StageFailures {
  count: number;
  rate: number | null;
}

/** PRD §49 reliability for one workspace and window. */
export interface ReliabilitySummary {
  workspace_id: number;
  days: number;
  source: string | null;
  /** Phase 4: sources left out when `source` was not given (evaluation runs are test traffic). */
  excluded_sources?: string[];
  since: string;
  runs: { total: number; completed: number; failed: number };
  failure_rate: number | null;
  failures_by_stage: { retrieval: StageFailures; generation: StageFailures; other: StageFailures };
  latency_ms: {
    sample_size: number;
    total: PercentileStat;
    retrieval: PercentileStat;
    generation: PercentileStat;
    first_token: PercentileStat;
  };
  tokens: { prompt: number; completion: number; total: number; runs_with_usage: number; average_per_run: number | null };
  ingestion: {
    documents: number;
    ready: number;
    failed: number;
    in_progress: number;
    not_indexed: number;
    success_rate: number | null;
    failure_rate: number | null;
    attempts: { total: number; succeeded: number; failed: number; failure_rate: number | null };
  };
}
