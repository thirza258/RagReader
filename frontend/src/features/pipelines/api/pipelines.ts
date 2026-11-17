import { apiClient } from "../../../services/apiClient";
import { results, unwrap } from "../../../services/api/request";
import type { IndexVersion, Pipeline, PipelineConfig, PipelineOptions, PipelineVersion } from "../types";

/** A workspace's pipelines, default first (the server creates the default on first use). */
export async function listPipelines(workspaceId: number, signal?: AbortSignal): Promise<Pipeline[]> {
  return results<Pipeline>(await unwrap(apiClient.get("/pipelines/", { params: { workspace_id: workspaceId }, signal })));
}

export function getPipelineOptions(signal?: AbortSignal): Promise<PipelineOptions> {
  return unwrap(apiClient.get<PipelineOptions>("/pipelines/options/", { signal }));
}

/** Version 1 is the defaults plus `config`. */
export function createPipeline(input: { workspaceId: number; name: string; config: Partial<PipelineConfig> }): Promise<Pipeline> {
  return unwrap(apiClient.post<Pipeline>("/pipelines/", { workspace_id: input.workspaceId, name: input.name, config: input.config }));
}

/** A changed configuration adds a version (`version_created`); a rename alone does not. */
export function updatePipeline(id: number, patch: { name?: string; config?: Partial<PipelineConfig> }): Promise<Pipeline> {
  return unwrap(apiClient.patch<Pipeline>(`/pipelines/${id}/`, patch));
}

export async function deletePipeline(id: number): Promise<void> {
  await unwrap(apiClient.delete(`/pipelines/${id}/`));
}

/** Newest first. */
export async function listPipelineVersions(id: number, signal?: AbortSignal): Promise<PipelineVersion[]> {
  return results<PipelineVersion>(await unwrap(apiClient.get(`/pipelines/${id}/versions/`, { signal })));
}

/** A document's index versions, newest first. */
export async function listIndexVersions(documentId: number, signal?: AbortSignal): Promise<IndexVersion[]> {
  return results<IndexVersion>(await unwrap(apiClient.get("/indexes/", { params: { document_id: documentId }, signal })));
}
