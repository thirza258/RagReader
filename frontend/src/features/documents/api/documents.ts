import type { AxiosResponse } from "axios";
import { apiClient } from "../../../services/apiClient";
import { ApiRequestError } from "../../../services/api/errors";
import { results, toApiErrorReadingBlob, unwrap } from "../../../services/api/request";
import type { DocumentText, IngestionStatus, NewDocumentInput, WorkspaceDocument } from "../types";

/** Newest first; the default workspace when `workspaceId` is omitted. */
export async function listDocuments(workspaceId: number | null, signal?: AbortSignal): Promise<WorkspaceDocument[]> {
  const params = workspaceId != null ? { workspace_id: workspaceId } : undefined;
  return results<WorkspaceDocument>(await unwrap(apiClient.get("/documents/", { params, signal })));
}

export function getDocument(id: number, signal?: AbortSignal): Promise<WorkspaceDocument> {
  return unwrap(apiClient.get<WorkspaceDocument>(`/documents/${id}/`, { signal }));
}

export interface CreateDocumentResult {
  document: WorkspaceDocument;
  /**
   * Set when the document was stored but could not be queued (503
   * `job_queue_unavailable`): it exists, FAILED and retryable.
   */
  warning: ApiRequestError | null;
}

export interface CreateDocumentOptions {
  workspaceId?: number | null;
  onUploadProgress?: (fraction: number) => void;
  signal?: AbortSignal;
}

function looksLikeDocument(value: unknown): value is WorkspaceDocument {
  return typeof value === "object" && value !== null && typeof (value as { id?: unknown }).id === "number" && typeof (value as { status?: unknown }).status === "string";
}

/** The document a 503 response may carry, either as the body or under `document`. */
function documentInErrorBody(body: unknown): WorkspaceDocument | null {
  if (looksLikeDocument(body)) return body;
  const nested = (body as { document?: unknown } | null)?.document;
  return looksLikeDocument(nested) ? nested : null;
}

/**
 * `POST documents/` (202). Files go as multipart; URLs and pasted text go as
 * JSON with `source_type`, so a URL is never uploaded as if it were a file.
 */
export async function createDocument(input: NewDocumentInput, options: CreateDocumentOptions = {}): Promise<CreateDocumentResult> {
  const title = input.title?.trim() || undefined;
  const workspace_id = options.workspaceId ?? undefined;
  let request: Promise<AxiosResponse<WorkspaceDocument>>;
  if (input.kind === "file") {
    const form = new FormData();
    form.append("file", input.file);
    if (title) form.append("title", title);
    if (workspace_id != null) form.append("workspace_id", String(workspace_id));
    request = apiClient.post<WorkspaceDocument>("/documents/", form, {
      // Large uploads on slow links outlast the default 30 s timeout.
      timeout: 10 * 60 * 1000,
      signal: options.signal,
      onUploadProgress: (event) => {
        if (options.onUploadProgress && event.total) options.onUploadProgress(Math.min(1, event.loaded / event.total));
      },
    });
  } else if (input.kind === "url") {
    request = apiClient.post<WorkspaceDocument>("/documents/", { source_type: "url", url: input.url, title, workspace_id }, { signal: options.signal });
  } else {
    request = apiClient.post<WorkspaceDocument>("/documents/", { source_type: "text", text: input.text, title, workspace_id }, { signal: options.signal, timeout: 120000 });
  }
  try {
    return { document: await unwrap(request), warning: null };
  } catch (error) {
    const apiError = error instanceof ApiRequestError ? error : await toApiErrorReadingBlob(error);
    // A 503 may still carry the stored (FAILED, retryable) document.
    const stored = documentInErrorBody(apiError.body);
    if (stored) return { document: stored, warning: apiError };
    throw apiError;
  }
}

export function renameDocument(id: number, title: string): Promise<WorkspaceDocument> {
  return unwrap(apiClient.patch<WorkspaceDocument>(`/documents/${id}/`, { title }));
}

export async function deleteDocument(id: number): Promise<void> {
  await unwrap(apiClient.delete(`/documents/${id}/`));
}

export function getIngestionStatus(id: number): Promise<IngestionStatus> {
  return unwrap(apiClient.get<IngestionStatus>(`/documents/${id}/ingestion/`));
}

/** Retry a failed ingestion or re-index a ready document (409 if a job is live). */
export function startIngestion(id: number): Promise<IngestionStatus> {
  return unwrap(apiClient.post<IngestionStatus>(`/documents/${id}/ingestion/`));
}

export function getDocumentText(id: number, signal?: AbortSignal): Promise<DocumentText> {
  return unwrap(apiClient.get<DocumentText>(`/documents/${id}/text/`, { signal, timeout: 60000 }));
}

/** The original upload, fetched with the token so it can be shown from a blob URL. */
export async function fetchDocumentFile(id: number, signal?: AbortSignal): Promise<Blob> {
  try {
    const response = await apiClient.get<Blob>(`/documents/${id}/file/`, { responseType: "blob", signal, timeout: 120000 });
    return response.data;
  } catch (error) {
    throw await toApiErrorReadingBlob(error);
  }
}
