import { apiClient } from "../../../services/apiClient";
import { unwrap } from "../../../services/api/request";
import type { ReliabilitySummary, RetrievalRunDetail, RunList, RunStatus } from "../types";

export interface RunListQuery {
  workspaceId: number;
  conversationId?: number;
  status?: RunStatus;
  limit?: number;
}

/** Newest first, at most `limit` (server default 50). */
export async function listRuns(query: RunListQuery, signal?: AbortSignal): Promise<RunList> {
  const body = await unwrap(
    apiClient.get<RunList>("/retrieval/runs/", {
      params: {
        workspace_id: query.workspaceId,
        ...(query.conversationId != null ? { conversation_id: query.conversationId } : {}),
        ...(query.status ? { status: query.status } : {}),
        ...(query.limit != null ? { limit: query.limit } : {}),
      },
      signal,
    }),
  );
  return { results: Array.isArray(body?.results) ? body.results : [], has_more: !!body?.has_more };
}

/** One run with provenance, spans and candidates. */
export function getRun(id: number, signal?: AbortSignal): Promise<RetrievalRunDetail> {
  return unwrap(apiClient.get<RetrievalRunDetail>(`/retrieval/runs/${id}/`, { signal }));
}

export function getRunSummary(workspaceId: number, days: number, signal?: AbortSignal): Promise<ReliabilitySummary> {
  return unwrap(apiClient.get<ReliabilitySummary>("/retrieval/runs/summary/", { params: { workspace_id: workspaceId, days }, signal }));
}
