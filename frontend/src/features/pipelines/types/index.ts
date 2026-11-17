/** Shapes of the pipeline and index-version endpoints (docs/prd-implementation.md, Phase 3). */

export type PipelineStrategy = "dense" | "bm25" | "hybrid" | "hybrid_rerank";
export type FusionMethod = "weighted" | "rrf";
export type RerankerProvider = "ollama" | "llm";

export interface RerankerSpec {
  provider: RerankerProvider | string;
  model: string;
}

/** A full pipeline configuration (every version stores all of it). */
export interface PipelineConfig {
  strategy: PipelineStrategy | string;
  fusion: FusionMethod | string;
  hybrid_weight: number;
  rrf_k: number;
  candidate_k: number;
  top_k: number;
  reranker: RerankerSpec | null;
  generation_model: string;
  temperature: number;
  prompt_version: string;
  embedding_model: string;
}

export type PipelineConfigKey = keyof PipelineConfig;

export interface PipelineVersion {
  id: number;
  pipeline_id: number;
  number: number;
  config: PipelineConfig;
  config_hash: string;
  created_at: string;
}

export interface PipelineVersionRef {
  id: number;
  number: number;
  created_at: string;
}

export interface Pipeline {
  id: number;
  workspace_id: number;
  name: string;
  is_default: boolean;
  /** The latest version: what the next question runs with. */
  version: PipelineVersion;
  version_count: number;
  /** Newest first. */
  versions: PipelineVersionRef[];
  created_at: string;
  updated_at: string;
  /** PATCH only: whether the edit added a version. */
  version_created?: boolean;
}

export interface Choice {
  id: string;
  label: string;
  description?: string;
}

export interface RerankerProviderOption extends Choice {
  /** Any well-formed OpenRouter id is accepted (the LLM reranker), not only `models`. */
  open: boolean;
  models: Choice[];
  default_model: string;
}

export interface NumberRange {
  min: number;
  max: number;
}

export interface PipelineOptions {
  strategies: (Choice & { uses?: string[] })[];
  fusion_methods: Choice[];
  reranker_providers: RerankerProviderOption[];
  generation_models: (Choice & { provider?: string })[];
  embedding_models: string[];
  prompt_versions: string[];
  ranges: Record<"candidate_k" | "top_k" | "rrf_k" | "hybrid_weight" | "temperature", NumberRange>;
  defaults: PipelineConfig;
  default_reranker: RerankerSpec;
  keys: string[];
}

/** `retrieval.pipeline_version` on an answer and `pipeline` on a run. */
export interface PipelineVersionLabel {
  name?: string | null;
  number?: number | null;
  version?: number | null;
}

/** A built index of a document (PRD §19). */
export interface IndexVersion {
  id: number;
  document_id: number;
  document_title: string;
  method: string;
  status: string;
  is_current: boolean;
  /** Known for the current index only (recorded at ingest time). */
  embedding_model: string | null;
  chunk_config: { strategy?: string; chunk_size?: number; overlap?: number } | null;
  chunk_count: number | null;
  created_at: string;
  updated_at: string;
}
