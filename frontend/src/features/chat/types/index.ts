/** Shapes of the conversation endpoints in docs/prd-implementation.md. */

export interface Conversation {
  id: number;
  workspace_id: number;
  title: string;
  /** Empty means "every READY document in the workspace". */
  document_ids: number[];
  message_count: number;
  last_message_preview: string | null;
  created_at: string;
  updated_at: string;
}

/** A source given to the model (PRD §14). `citation_id` is its `[n]`. */
export interface Evidence {
  citation_id: number;
  document_id: number;
  document_title: string;
  index_version_id: number | null;
  chunk_id: number | string | null;
  page_number: number | null;
  page_end: number | null;
  char_start: number | null;
  char_end: number | null;
  text: string;
  retrieval_score: number | null;
  rerank_score: number | null;
  cited: boolean;
  /** Client-side only: set when a retrieved candidate (not a cited source) is opened in the reader. */
  candidate_rank?: number | null;
}

export interface RetrievalPipeline {
  strategy?: string;
  embedding_model?: string;
  generation_model?: string;
  temperature?: number | null;
  candidate_k?: number;
  top_k?: number;
  prompt_version?: string;
}

export interface RetrievalCandidate {
  document_id: number;
  chunk_id: number | string;
  retrieval_score: number | null;
  rank: number;
}

export interface RetrievalTimings {
  rewrite?: number | null;
  embed_query?: number | null;
  search?: number | null;
  first_token?: number | null;
  generation?: number | null;
  total?: number | null;
}

/** Phase 1 retrieval metadata; later phases only add fields. */
export interface RetrievalMetadata {
  pipeline?: RetrievalPipeline;
  query?: { original?: string; rewritten?: string; rewrite_applied?: boolean };
  documents?: { document_id: number; index_version_id: number | null }[];
  candidates?: RetrievalCandidate[];
  candidate_count?: number | null;
  context_count?: number | null;
  cited_count?: number | null;
  timings_ms?: RetrievalTimings;
  /** Phase 2: the retrieval run recorded for this answer (GET /retrieval/runs/{id}/). */
  run_id?: number | null;
}

export interface TokenUsage {
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
}

export interface MessageError {
  code: string;
  message: string;
  retryable?: boolean;
  stage?: string | null;
}

export type MessageRole = "user" | "assistant";
export type MessageStatus = "streaming" | "complete" | "failed";

export interface ChatMessage {
  id: number;
  conversation_id: number;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  citations: Evidence[];
  retrieval: RetrievalMetadata | null;
  token_usage: TokenUsage | null;
  latency_ms: number | null;
  error: MessageError | null;
  analysis_turn: { conversation_id: number; document_id: number } | null;
  created_at: string;
}

export type StreamStageStatus = "running" | "completed" | "skipped" | "failed";

/** One `stage` event: rewrite, retrieve or generate. */
export interface StreamStage {
  id: string;
  status: StreamStageStatus;
  detail: string;
  duration_ms: number | null;
}

/** The SSE events of `POST conversations/{id}/messages/`, parsed and checked. */
export type ChatStreamEvent =
  | { type: "message.created"; userMessage: ChatMessage | null; assistantMessage: ChatMessage | null }
  | { type: "stage"; stage: StreamStage }
  | { type: "retrieval"; candidateCount: number | null; contextCount: number | null; citations: Evidence[] }
  | { type: "token"; delta: string }
  | { type: "message.completed"; message: ChatMessage }
  | { type: "error"; error: MessageError; message: ChatMessage | null };
