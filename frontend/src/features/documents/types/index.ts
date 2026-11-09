/** Shapes of the document endpoints in docs/prd-implementation.md. */

export type DocumentStatus =
  | "UPLOADING"
  | "QUEUED"
  | "EXTRACTING"
  | "CLEANING"
  | "CHUNKING"
  | "EMBEDDING"
  | "INDEXING"
  | "READY"
  | "FAILED";

/** `markdown` only appears on rows created before the workspace API. */
export type SourceType = "pdf" | "docx" | "txt" | "md" | "markdown" | "url" | "text";

export interface DocumentError {
  code: string;
  message: string;
  retryable: boolean;
  stage: string | null;
}

export interface DocumentIndexInfo {
  id: number;
  method: string;
  embedding_model: string;
  created_at: string;
}

export interface WorkspaceDocument {
  id: number;
  workspace_id: number;
  title: string;
  source_type: SourceType | string;
  /** Original filename, the URL, or null for pasted text. */
  source: string | null;
  mime_type: string;
  file_size: number | null;
  has_original_file: boolean;
  status: DocumentStatus;
  status_detail: string;
  progress: number;
  error: DocumentError | null;
  page_count: number | null;
  chunk_count: number | null;
  char_count: number | null;
  index: DocumentIndexInfo | null;
  created_at: string;
  updated_at: string;
  ingested_at: string | null;
}

export type IngestionStageState = "done" | "active" | "pending" | "failed";

export interface IngestionStage {
  id: string;
  label: string;
  state: IngestionStageState;
}

export interface IngestionStatus {
  document_id: number;
  status: DocumentStatus;
  progress: number;
  status_detail: string;
  stages: IngestionStage[];
  job: { id: string; status: string; updated_at: string } | null;
  error: DocumentError | null;
  can_retry: boolean;
}

/** One PDF page inside the extracted text: `text.slice(start, end)`. */
export interface PageSpan {
  number: number;
  start: number;
  end: number;
}

export interface DocumentText {
  document_id: number;
  text: string;
  pages: PageSpan[];
  char_count: number;
  truncated: boolean;
}

/** What the upload panels hand to `createDocument`. */
export type NewDocumentInput =
  | { kind: "file"; file: File; title?: string }
  | { kind: "url"; url: string; title?: string }
  | { kind: "text"; text: string; title?: string };
