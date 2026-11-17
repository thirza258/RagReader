import { apiClient } from "../../../services/apiClient";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { results, toApiErrorReadingBlob, unwrap } from "../../../services/api/request";
import type { ResearchOptions, ResearchTask } from "../types";

/** Research endpoints (docs/workspace-api.md, Research tasks). */

export async function listResearchTasks(workspaceId: number, signal?: AbortSignal): Promise<ResearchTask[]> {
  return results<ResearchTask>(await unwrap(apiClient.get("/research/tasks/", { params: { workspace_id: workspaceId }, signal })));
}

export function getResearchTask(id: number, signal?: AbortSignal): Promise<ResearchTask> {
  return unwrap(apiClient.get<ResearchTask>(`/research/tasks/${id}/`, { signal }));
}

export function getResearchOptions(signal?: AbortSignal): Promise<ResearchOptions> {
  return unwrap(apiClient.get<ResearchOptions>("/research/options/", { signal }));
}

export interface QueuedTask {
  task: ResearchTask;
  /** Set when the task was saved but its worker was unreachable (503): it is failed and can be retried. */
  warning: ApiRequestError | null;
}

function looksLikeTask(value: unknown): value is ResearchTask {
  return typeof value === "object" && value !== null && typeof (value as { id?: unknown }).id === "number"
    && typeof (value as { kind?: unknown }).kind === "string";
}

async function queued(request: Promise<{ data: ResearchTask }>): Promise<QueuedTask> {
  try {
    return { task: (await request).data, warning: null };
  } catch (caught) {
    const error = toApiError(caught);
    const nested = (error.body as { task?: unknown } | null)?.task;
    if (error.status === 503 && looksLikeTask(nested)) return { task: nested, warning: error };
    throw error;
  }
}

export function createResearchTask(payload: Record<string, unknown>): Promise<QueuedTask> {
  return queued(apiClient.post<ResearchTask>("/research/tasks/", payload));
}

export function retryResearchTask(id: number): Promise<QueuedTask> {
  return queued(apiClient.post<ResearchTask>(`/research/tasks/${id}/retry/`));
}

export function cancelResearchTask(id: number): Promise<ResearchTask> {
  return unwrap(apiClient.post<ResearchTask>(`/research/tasks/${id}/cancel/`));
}

export function updateResearchTask(id: number, patch: { title?: string; notes?: string }): Promise<ResearchTask> {
  return unwrap(apiClient.patch<ResearchTask>(`/research/tasks/${id}/`, patch));
}

export async function deleteResearchTask(id: number): Promise<void> {
  await unwrap(apiClient.delete(`/research/tasks/${id}/`));
}

/** Downloads `research-<id>.md|json` (fetched with the token). */
export async function exportResearchTask(id: number, format: "md" | "json"): Promise<void> {
  let response;
  try {
    response = await apiClient.get<Blob>(`/research/tasks/${id}/export/`, { params: { format }, responseType: "blob" });
  } catch (error) {
    throw await toApiErrorReadingBlob(error);
  }
  const url = URL.createObjectURL(response.data);
  try {
    const link = window.document.createElement("a");
    link.href = url;
    link.download = `research-${id}.${format}`;
    link.rel = "noopener";
    window.document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
