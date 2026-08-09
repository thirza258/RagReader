import { OnErrorCallback, OnProgressCallback, OnResultCallback } from "./services/websocket";

export interface ChatResponse {
  status: number;
  message: string;
  timestamp: number;
  data: {
    answer: string;
    context?: string[];
    conversation_id?: string;
    document_id?: string;
  };
}

export interface RetrievedChunk {
  id: string | number;
  text: string;
  score?: number;
}

export interface EvaluationMetric {
  chunk_evaluation: Record<string, number>;
    response_evaluation: Record<string, number | string>;
    retrieval_score?: { chunk_id: string; score: number }[];
}

export interface AnalysisResult {
  batch_id: string;
  method: string;
  aiModel: string;
  query: string;
  answer: string;
  retrievedChunks: RetrievedChunk[];
  evaluation?: EvaluationMetric;
  progress: number;
  error?: string;
}

export interface WebSocketMessage {
  status?: string;
  method?: string;
  query?: string;
  aiModel?: string;
  progress?: number;
  batch_id?: string;
  error?: string;
  answer?: string;
  context?: {
    text: string;
    chunk_id: number | string;
    score?: number;
  }[];
  evaluation?: EvaluationMetric;
}

export interface NormalizedChunk {
  number: number;
  id: string | number;
  text: string;
  score?: number;
}

export interface DeepAnalysisServiceOptions {
  url: string;
  query?: string;
  onOpen?: () => void;
  onResult: OnResultCallback;
  onProgress?: OnProgressCallback;
  onError?: OnErrorCallback;
  onClose?: () => void;
}


export interface StartAnalysisResponse {
  message: string;
  batch_id: string;
  document_id: string;
  query: string;
  expected_count: number;
  config: DeepAnalysisConfig;
  /** What the retrieval metrics will actually be scored against. */
  ground_truth: { count: number; source: GroundTruthMode | null };
}

export interface HistoryItem {
  id: string;
  title: string;
  type: "file" | "url";
  date: string; 
}

export interface TaskData {
  id: string;
  prompt: string;
}

export interface Chunk {
  id: string;
  text: string;
}

/** How the ground-truth chunk set for a conversation was decided. */
export type GroundTruthMode = "manual" | "pooled";

/**
 * Deep-analysis configuration. Field names match the backend payload exactly
 * so the config round-trips without a mapping layer.
 */
export interface DeepAnalysisConfig {
  methods: string[];
  models: string[];
  top_k: number;
  ground_truth_mode: GroundTruthMode;
  pool_top_n: number;
}

export interface AnalysisOption {
  id: string;
  label: string;
  description?: string;
  provider?: string;
}

/** Served by GET /analysis-config/ — never hardcode these in the UI. */
export interface AnalysisConfigOptions {
  retrieval_methods: AnalysisOption[];
  models: AnalysisOption[];
  ground_truth_modes: AnalysisOption[];
  top_k: { min: number; max: number; default: number };
  pool_top_n: { min: number; max: number; default: number };
  defaults: DeepAnalysisConfig;
  max_variants: number;
}

/** One retriever's contribution to a pooled chunk's RRF score. */
export interface PooledChunkSource {
  pipeline: string;
  rank: number;
  score?: number | null;
}

export interface PooledChunk {
  chunk_id: number | string;
  text: string;
  rank: number;
  rrf_score: number;
  sources: PooledChunkSource[];
}

export interface CandidatePoolResponse {
  conversation_id: number;
  source: "pooled";
  query: string;
  optimized_query: string;
  rrf_k: number;
  top_n: number;
  pipelines: { name: string; retrieved: number; error: string | null }[];
  chunks: PooledChunk[];
}

export interface GroundTruthChunkRecord {
  id: number;
  chunk_id: number;
  text: string;
  source: GroundTruthMode;
  rank: number | null;
  rrf_score: number | null;
  sources: PooledChunkSource[];
}

export interface GroundTruthChunkResponse {
  ground_truth_chunks: GroundTruthChunkRecord[];
  source: GroundTruthMode | null;
}

export interface FileMetadata {
  id: string;
  name: string;
  source_type: string;
  source_path: string;
  extracted_text_path: string;
  created_at: string;
}

export interface ConversationItem {
  query: string;
  response: string;
  created_at: string;
}