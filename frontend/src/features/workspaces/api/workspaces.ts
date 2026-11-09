import { apiClient } from "../../../services/apiClient";
import { results, unwrap } from "../../../services/api/request";
import type { Workspace } from "../types";

/** Creates the user's default workspace on first call. */
export async function listWorkspaces(signal?: AbortSignal): Promise<Workspace[]> {
  return results<Workspace>(await unwrap(apiClient.get("/workspaces/", { signal })));
}

export function createWorkspace(name: string): Promise<Workspace> {
  return unwrap(apiClient.post<Workspace>("/workspaces/", { name }));
}

export function renameWorkspace(id: number, name: string): Promise<Workspace> {
  return unwrap(apiClient.patch<Workspace>(`/workspaces/${id}/`, { name }));
}

/** 409 `last_workspace` when it is the only one left. */
export async function deleteWorkspace(id: number): Promise<void> {
  await unwrap(apiClient.delete(`/workspaces/${id}/`));
}
