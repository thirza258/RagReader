import { apiClient } from "../../../services/apiClient";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { results, toApiErrorReadingBlob, unwrap } from "../../../services/api/request";
import { compareIdsParam } from "../lib/comparison";
import type {
  Comparison,
  ComparisonQuery,
  Dataset,
  DatasetItem,
  DatasetItemInput,
  DatasetItemsPage,
  DatasetVersionsPage,
  Experiment,
  ExperimentDetail,
  ExperimentInput,
  ExperimentItemsPage,
  ExperimentItemsQuery,
  ExperimentStatus,
  FromMessageDraft,
  ImportFormat,
  ImportMode,
  ImportResult,
  ItemsWriteResult,
} from "../types";

/** Evaluation lab endpoints (docs/prd-implementation.md, Phase 4). */

// ── Datasets ────────────────────────────────────────────────────────────────

/** Most recently updated first; the default workspace when `workspaceId` is null. */
export async function listDatasets(workspaceId: number | null, signal?: AbortSignal): Promise<Dataset[]> {
  const params = workspaceId != null ? { workspace_id: workspaceId } : undefined;
  return results<Dataset>(await unwrap(apiClient.get("/evaluations/datasets/", { params, signal })));
}

export function createDataset(input: { workspaceId: number; name: string; description?: string; documentIds?: number[]; items?: DatasetItemInput[] }): Promise<Dataset> {
  return unwrap(
    apiClient.post<Dataset>("/evaluations/datasets/", {
      workspace_id: input.workspaceId,
      name: input.name,
      ...(input.description ? { description: input.description } : {}),
      ...(input.documentIds ? { document_ids: input.documentIds } : {}),
      ...(input.items ? { items: input.items } : {}),
    }),
  );
}

export function getDataset(id: number, signal?: AbortSignal): Promise<Dataset> {
  return unwrap(apiClient.get<Dataset>(`/evaluations/datasets/${id}/`, { signal }));
}

export interface DatasetPatch {
  name?: string;
  description?: string;
  document_ids?: number[];
  /** Replaces the whole item list (a new version when the content changes). */
  items?: DatasetItemInput[];
  base_version?: number;
}

/** Renaming never adds a version; changing items or documents may (`version_created`). */
export function updateDataset(id: number, patch: DatasetPatch): Promise<Dataset> {
  return unwrap(apiClient.patch<Dataset>(`/evaluations/datasets/${id}/`, patch));
}

export async function deleteDataset(id: number): Promise<void> {
  await unwrap(apiClient.delete(`/evaluations/datasets/${id}/`));
}

/** Every version, newest first. */
export function listDatasetVersions(id: number, signal?: AbortSignal): Promise<DatasetVersionsPage> {
  return unwrap(apiClient.get<DatasetVersionsPage>(`/evaluations/datasets/${id}/versions/`, { signal }));
}

/** The items of one version (the latest when `version` is null). */
export function listDatasetItems(id: number, version: number | null, signal?: AbortSignal): Promise<DatasetItemsPage> {
  const params = version != null ? { version } : undefined;
  return unwrap(apiClient.get<DatasetItemsPage>(`/evaluations/datasets/${id}/items/`, { params, signal }));
}

/** Appends items: a new version. */
export function addDatasetItems(id: number, items: DatasetItemInput[], baseVersion?: number | null): Promise<ItemsWriteResult> {
  return unwrap(
    apiClient.post<ItemsWriteResult>(`/evaluations/datasets/${id}/items/`, {
      items,
      ...(baseVersion != null ? { base_version: baseVersion } : {}),
    }),
  );
}

/** Edits one item: a new version. */
export function updateDatasetItem(id: number, itemId: string, patch: Partial<DatasetItemInput>, baseVersion?: number | null): Promise<ItemsWriteResult & { item: DatasetItem }> {
  return unwrap(
    apiClient.patch<ItemsWriteResult & { item: DatasetItem }>(`/evaluations/datasets/${id}/items/${encodeURIComponent(itemId)}/`, {
      ...patch,
      ...(baseVersion != null ? { base_version: baseVersion } : {}),
    }),
  );
}

/** Removes one item: a new version. */
export function deleteDatasetItem(id: number, itemId: string): Promise<ItemsWriteResult> {
  return unwrap(apiClient.delete<ItemsWriteResult>(`/evaluations/datasets/${id}/items/${encodeURIComponent(itemId)}/`));
}

export interface ImportInput {
  format: ImportFormat;
  /** The file's text; the server parses it with the same rules as the preview. */
  content: string;
}

/** A new dataset from a JSON or CSV file. */
export function importNewDataset(input: ImportInput & { workspaceId: number; name?: string }): Promise<ImportResult> {
  return unwrap(
    apiClient.post<ImportResult>(
      "/evaluations/datasets/import/",
      { workspace_id: input.workspaceId, format: input.format, content: input.content, ...(input.name ? { name: input.name } : {}) },
      { timeout: 120000 },
    ),
  );
}

/** Items from a file into an existing dataset: appended or replacing the list (a new version). */
export function importIntoDataset(id: number, input: ImportInput & { mode: ImportMode; baseVersion?: number | null }): Promise<ImportResult> {
  return unwrap(
    apiClient.post<ImportResult>(
      `/evaluations/datasets/${id}/import/`,
      {
        format: input.format,
        content: input.content,
        mode: input.mode,
        ...(input.baseVersion != null ? { base_version: input.baseVersion } : {}),
      },
      { timeout: 120000 },
    ),
  );
}

function filenameFrom(disposition: unknown, fallback: string): string {
  if (typeof disposition !== "string") return fallback;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      /* fall through to the plain form */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain ? plain[1].trim() : fallback;
}

/** Downloads `dataset-<id>-v<n>.json|csv` (fetched with the token, saved by the browser). */
export async function exportDataset(id: number, format: ImportFormat, version?: number | null): Promise<string> {
  let response;
  try {
    response = await apiClient.get<Blob>(`/evaluations/datasets/${id}/export/`, {
      params: { format, ...(version != null ? { version } : {}) },
      responseType: "blob",
      timeout: 120000,
    });
  } catch (error) {
    throw await toApiErrorReadingBlob(error);
  }
  const filename = filenameFrom(response.headers?.["content-disposition"], `dataset-${id}${version != null ? `-v${version}` : ""}.${format}`);
  const url = URL.createObjectURL(response.data);
  try {
    const link = window.document.createElement("a");
    link.href = url;
    link.download = filename;
    link.rel = "noopener";
    window.document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return filename;
}

/** A draft item from a chat answer; nothing is written until it is posted. */
export function getDraftFromMessage(datasetId: number, messageId: number, signal?: AbortSignal): Promise<FromMessageDraft> {
  return unwrap(apiClient.get<FromMessageDraft>(`/evaluations/datasets/${datasetId}/items/from-message/`, { params: { message_id: messageId }, signal }));
}

// ── Experiments ─────────────────────────────────────────────────────────────

export interface ExperimentListQuery {
  workspaceId: number;
  datasetId?: number | null;
  status?: ExperimentStatus | null;
}

/** Newest first. */
export async function listExperiments(query: ExperimentListQuery, signal?: AbortSignal): Promise<Experiment[]> {
  return results<Experiment>(
    await unwrap(
      apiClient.get("/experiments/", {
        params: {
          workspace_id: query.workspaceId,
          ...(query.datasetId != null ? { dataset_id: query.datasetId } : {}),
          ...(query.status ? { status: query.status } : {}),
        },
        signal,
      }),
    ),
  );
}

export interface StartResult {
  experiment: Experiment;
  /**
   * Set when the experiment was saved but could not be queued (503
   * `job_queue_unavailable`): it exists, failed and resumable.
   */
  warning: ApiRequestError | null;
}

function looksLikeExperiment(value: unknown): value is Experiment {
  return typeof value === "object" && value !== null && typeof (value as { id?: unknown }).id === "number" && typeof (value as { status?: unknown }).status === "string";
}

/** A 202/201 experiment, or the experiment a 503 carries under `experiment`. */
async function startRequest(request: Promise<{ data: Experiment }>): Promise<StartResult> {
  try {
    return { experiment: (await request).data, warning: null };
  } catch (caught) {
    const error = toApiError(caught);
    const nested = (error.body as { experiment?: unknown } | null)?.experiment;
    if (error.status === 503 && looksLikeExperiment(nested)) return { experiment: nested, warning: error };
    throw error;
  }
}

/** Queued (202), or a draft (201) with `draft: true`. */
export function createExperiment(input: ExperimentInput): Promise<StartResult> {
  return startRequest(apiClient.post<Experiment>("/experiments/", input));
}

export function getExperiment(id: number, signal?: AbortSignal): Promise<ExperimentDetail> {
  return unwrap(apiClient.get<ExperimentDetail>(`/experiments/${id}/`, { signal }));
}

export function updateExperiment(id: number, patch: { name?: string; hypothesis?: string; conclusion?: string }): Promise<ExperimentDetail> {
  return unwrap(apiClient.patch<ExperimentDetail>(`/experiments/${id}/`, patch));
}

/** Also deletes its evaluation runs; a running experiment stops. */
export async function deleteExperiment(id: number): Promise<void> {
  await unwrap(apiClient.delete(`/experiments/${id}/`));
}

/** First start of a draft, or resume of a failed/cancelled run (completed items are kept). */
export function startExperiment(id: number): Promise<StartResult> {
  return startRequest(apiClient.post<Experiment>(`/experiments/${id}/start/`));
}

export function cancelExperiment(id: number): Promise<Experiment> {
  return unwrap(apiClient.post<Experiment>(`/experiments/${id}/cancel/`));
}

/** A new experiment with the stored configuration (§42). */
export function rerunExperiment(id: number, options: { name?: string; draft?: boolean } = {}): Promise<StartResult> {
  return startRequest(apiClient.post<Experiment>(`/experiments/${id}/rerun/`, options));
}

export function listExperimentItems(id: number, query: ExperimentItemsQuery = {}, signal?: AbortSignal): Promise<ExperimentItemsPage> {
  return unwrap(
    apiClient.get<ExperimentItemsPage>(`/experiments/${id}/items/`, {
      params: {
        ...(query.status ? { status: query.status } : {}),
        ...(query.category ? { category: query.category } : {}),
        ...(query.label ? { label: query.label } : {}),
        ...(query.offset != null ? { offset: query.offset } : {}),
        ...(query.limit != null ? { limit: query.limit } : {}),
      },
      signal,
    }),
  );
}

/** §30: 2–6 experiments on the same dataset against a baseline. */
export function compareExperiments(query: ComparisonQuery, signal?: AbortSignal): Promise<Comparison> {
  return unwrap(
    apiClient.get<Comparison>("/experiments/compare/", {
      params: {
        ids: compareIdsParam(query.ids),
        ...(query.baseline != null ? { baseline: query.baseline } : {}),
        ...(query.metric ? { metric: query.metric } : {}),
        ...(query.seed != null ? { seed: query.seed } : {}),
      },
      signal,
      timeout: 60000,
    }),
  );
}
