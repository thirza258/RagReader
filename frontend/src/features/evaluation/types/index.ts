/** Shapes of the evaluation-lab endpoints (docs/prd-implementation.md, Phase 4). */
import type { Evidence, TokenUsage } from "../../chat/types/index.ts";
import type { PipelineConfig } from "../../pipelines/types/index.ts";

// ── Datasets ────────────────────────────────────────────────────────────────

/**
 * Where an answer to a dataset question should come from. Only the document
 * is required; the rest narrows it to a chunk, a character range or pages.
 * `document_title` is filled in by the server from the current title (null
 * once the document is gone) and may name the document on import.
 */
export interface ExpectedSource {
  document_id: number | null;
  document_title?: string | null;
  chunk_id: number | null;
  index_version_id: number | null;
  char_start: number | null;
  char_end: number | null;
  page: number | null;
  page_end: number | null;
  text: string;
}

export type HistoryRole = "user" | "assistant";

/** One earlier turn of the conversation a follow-up question belongs to. */
export interface HistoryTurn {
  role: HistoryRole;
  content: string;
}

export interface DatasetItem {
  /** Stable across versions (e.g. "q1"). */
  item_id: string;
  position: number;
  question: string;
  expected_answer: string;
  expected_sources: ExpectedSource[];
  history: HistoryTurn[];
  tags: string[];
  metadata: Record<string, unknown>;
}

/** What the client sends: everything but the question is optional. */
export interface DatasetItemInput {
  item_id?: string;
  question: string;
  expected_answer?: string;
  expected_sources?: ExpectedSource[];
  history?: HistoryTurn[];
  tags?: string[];
  metadata?: Record<string, unknown>;
}

/** Static problems of a version, computed on read (each list ≤ 50 ids). */
export interface VersionChecks {
  items_without_sources: string[];
  duplicate_questions: string[][];
  missing_documents: string[];
}

export interface DatasetVersion {
  id: number;
  dataset_id: number;
  number: number;
  content_hash: string;
  item_count: number;
  /** The corpus; empty = every READY document of the workspace when an experiment starts. */
  document_ids: number[];
  note: string;
  created_at: string;
  checks?: VersionChecks | null;
}

export interface DatasetVersionRef {
  id: number;
  number: number;
  item_count: number;
  content_hash: string;
  note: string;
  created_at: string;
}

export interface Dataset {
  id: number;
  workspace_id: number;
  name: string;
  description: string;
  /** The latest version. */
  version: DatasetVersion;
  version_count: number;
  /** Newest first. */
  versions: DatasetVersionRef[];
  experiment_count: number;
  created_at: string;
  updated_at: string;
  /** PATCH only: whether the change added a version. */
  version_created?: boolean;
}

export interface DatasetItemsPage {
  dataset_id: number;
  version: DatasetVersion;
  results: DatasetItem[];
}

export interface DatasetVersionsPage {
  dataset_id: number;
  results: DatasetVersion[];
}

export type ImportFormat = "json" | "csv";
export type ImportMode = "append" | "replace";

export interface ImportResult {
  /** Importing a new dataset. */
  dataset?: Dataset;
  /** Importing into an existing dataset. */
  version?: DatasetVersion;
  imported: number;
  ignored_columns: string[];
}

export interface ItemsWriteResult {
  version: DatasetVersion;
  items?: DatasetItem[];
  item?: DatasetItem;
}

/** A chat-answer source offered for the expected sources; `suggested` = cited. */
export interface DraftSource extends Evidence {
  suggested: boolean;
}

/** `GET …/items/from-message/`: nothing is written until the item is posted. */
export interface FromMessageDraft {
  draft: DatasetItemInput & { item_id?: string | null; position?: number | null };
  sources: DraftSource[];
  message_id: number;
  conversation_id: number;
}

// ── Experiments ─────────────────────────────────────────────────────────────

export type ExperimentStatus = "draft" | "queued" | "running" | "completed" | "failed" | "cancelled";
export type ItemStatus = "pending" | "completed" | "failed";
export type MetricGroup = "retrieval" | "generation";
export type FailureCategory = "retrieval" | "generation" | "dataset";

/** A metric over an experiment's items: the mean of the items with a value. */
export interface MetricAggregate {
  mean: number | null;
  count: number;
  null_count: number;
  /** Null reason → number of items. */
  reasons: Record<string, number>;
}

export interface LatencyAggregate {
  p50: number | null;
  p95: number | null;
  mean: number | null;
  count: number;
}

export interface Aggregates {
  items: { total: number; completed: number; failed: number };
  retrieval: Record<string, MetricAggregate>;
  generation: Record<string, MetricAggregate>;
  latency_ms: Partial<Record<"total" | "retrieval" | "generation" | "judge", LatencyAggregate>>;
  tokens: { prompt: number; completion: number; total: number; per_item: number | null; items_with_usage: number };
  cost: { usd: number | null; reason: string | null };
}

export interface FailureCounts {
  retrieval: Record<string, number>;
  generation: Record<string, number>;
  dataset: Record<string, number>;
  items_with_failures: number;
}

export interface ExperimentWarning {
  code: string;
  message: string;
  experiment_ids?: number[];
  document_id?: number | null;
  [key: string]: unknown;
}

export interface ExperimentDatasetRef {
  id: number | null;
  name: string;
  version_id: number | null;
  version: number | null;
  content_hash: string | null;
  item_count: number | null;
  /** False once the dataset version was deleted (the snapshot remains). */
  available: boolean;
}

export interface ExperimentPipelineRef {
  id: number | null;
  name: string;
  version_id: number | null;
  version: number | null;
  config_hash: string | null;
  strategy: string | null;
  available: boolean;
}

export interface ExperimentProgress {
  total: number;
  completed: number;
  failed: number;
  pending: number;
}

export interface ExperimentError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface Experiment {
  id: number;
  workspace_id: number;
  name: string;
  hypothesis: string;
  conclusion: string;
  status: ExperimentStatus;
  error: ExperimentError | null;
  dataset: ExperimentDatasetRef;
  pipeline: ExperimentPipelineRef;
  retrieval_only: boolean;
  seed: number;
  k_values: number[];
  progress: ExperimentProgress;
  /** Over the completed items so far (stored when the run ends). */
  metrics: Aggregates | null;
  failures: FailureCounts | null;
  warnings: ExperimentWarning[];
  git_commit: string | null;
  rerun_of: number | null;
  runtime_ms: number | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ExperimentConfig {
  schema_version: number;
  pipeline: {
    pipeline_id: number | null;
    name: string | null;
    version_id: number | null;
    version: number | null;
    config: PipelineConfig;
    config_hash: string | null;
  } | null;
  dataset: {
    dataset_id: number | null;
    name: string | null;
    version_id: number | null;
    version: number | null;
    content_hash: string | null;
    item_count: number | null;
  } | null;
  document_ids: number[];
  retrieval_only: boolean;
  query_rewrite: boolean;
  k_values: number[];
  judge_model: string | null;
  thresholds: { faithfulness: number; answer_correctness: number };
  seed: number;
}

export interface ExperimentIndexVersion {
  document_id: number;
  document_title: string;
  index_version_id: number | null;
  method: string | null;
  created_at: string | null;
  embedding_model: string | null;
}

export interface ExperimentEnvironment {
  python: string | null;
  packages: Record<string, string | null>;
  models: Record<string, unknown>;
}

export interface Reproducibility {
  status: "reproducible" | "changed";
  warnings: ExperimentWarning[];
}

export interface ExperimentDetail extends Experiment {
  config: ExperimentConfig;
  index_versions: ExperimentIndexVersion[];
  environment: ExperimentEnvironment;
  reproducibility: Reproducibility;
}

/** `POST experiments/`. */
export interface ExperimentInput {
  name: string;
  hypothesis?: string;
  workspace_id?: number;
  dataset_id: number;
  /** A version number; the latest when omitted. */
  dataset_version?: number;
  pipeline_version_id?: number;
  pipeline_id?: number;
  retrieval_only?: boolean;
  seed?: number;
  k_values?: number[];
  judge_model?: string;
  query_rewrite?: boolean;
  draft?: boolean;
}

export interface FailureLabel {
  category: FailureCategory | string;
  code: string;
  detail: string;
  /** Indexes into the item's expected sources. */
  sources: number[];
}

export type MatchRule = "chunk_id" | "char_overlap" | "page" | "document" | "unresolved";

export interface SourceMatch {
  source: number;
  rule: MatchRule | string;
  chunk_ids: number[];
  reason: string | null;
}

export interface RetrievedEntry {
  rank: number;
  document_id: number | null;
  chunk_id: number | null;
  in_context: boolean;
  cited?: boolean;
  relevant: boolean;
  sources: number[];
}

export interface ItemQuery {
  used: string;
  original: string;
  rewritten: string | null;
  rewrite_applied: boolean;
  rewrite_reason: string | null;
}

export interface ExperimentItem {
  position: number;
  item_id: string;
  status: ItemStatus;
  error: { code: string; message: string; stage: string | null } | null;
  question: string;
  expected_answer: string;
  expected_sources: ExpectedSource[];
  history: HistoryTurn[];
  tags: string[];
  run_id: number | null;
  answer: string | null;
  query: ItemQuery | null;
  matching: SourceMatch[];
  retrieved: RetrievedEntry[];
  alternative: { query: string; retrieved: RetrievedEntry[] } | null;
  metrics: Record<string, number | null>;
  metric_reasons: Record<string, string>;
  failure_labels: FailureLabel[];
  latency_ms: { total: number | null; retrieval: number | null; generation: number | null; judge: number | null } | null;
  token_usage: TokenUsage | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface ExperimentItemsPage {
  results: ExperimentItem[];
  count: number;
  offset: number;
  limit: number;
}

export interface ExperimentItemsQuery {
  status?: ItemStatus | null;
  category?: FailureCategory | null;
  label?: string | null;
  offset?: number;
  limit?: number;
}

// ── Comparison (§30) ────────────────────────────────────────────────────────

export interface ComparisonCell {
  experiment_id: number;
  mean: number | null;
  count: number;
  /** Mean − baseline mean; null on the baseline. */
  delta: number | null;
  /** Mean of the paired differences: the centre of the CI. */
  paired_delta: number | null;
  ci_low: number | null;
  ci_high: number | null;
  pairs: number | null;
  wins: number | null;
  losses: number | null;
  ties: number | null;
}

export interface ComparisonMetricRow {
  key: string;
  group: MetricGroup | string;
  higher_is_better: boolean;
  cells: ComparisonCell[];
}

export interface OperationalCell {
  experiment_id: number;
  value: number | null;
  delta: number | null;
}

export interface OperationalRow {
  key: string;
  higher_is_better: boolean;
  cells: OperationalCell[];
}

export type ItemOutcome = "win" | "loss" | "tie";

export interface ComparisonItemCell {
  experiment_id: number;
  value: number | null;
  outcome: ItemOutcome | null;
}

export interface ComparisonItemRow {
  item_id: string;
  question: string;
  cells: ComparisonItemCell[];
}

export interface Comparison {
  baseline_id: number;
  experiments: Experiment[];
  metrics: ComparisonMetricRow[];
  operational: OperationalRow[];
  items: { metric: string; rows: ComparisonItemRow[] };
  bootstrap: { seed: number; resamples: number; confidence: number };
  config_differences: { key: string; values: unknown[] }[];
  warnings: ExperimentWarning[];
}

export interface ComparisonQuery {
  ids: number[];
  baseline?: number | null;
  metric?: string | null;
  seed?: number | null;
}
