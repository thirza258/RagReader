import { useEffect, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { getRunSummary, listRuns } from "../api/runs";
import type { ReliabilitySummary, RetrievalRun } from "../types";

export const RUN_LIST_LIMIT = 50;

interface OverviewState {
  key: string;
  runs: RetrievalRun[];
  hasMore: boolean;
  summary: ReliabilitySummary | null;
  error: ApiRequestError | null;
}

/**
 * A workspace's recent runs and its reliability summary (PRD §32, §49),
 * read together. `version` re-reads them, e.g. after a chat turn finishes.
 */
export function useRunsOverview(workspaceId: number, days: number, version: number) {
  const key = `${workspaceId}:${days}:${version}`;
  const [state, setState] = useState<OverviewState | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      listRuns({ workspaceId, limit: RUN_LIST_LIMIT }, controller.signal),
      getRunSummary(workspaceId, days, controller.signal),
    ]).then(
      ([list, summary]) => setState({ key, runs: list.results, hasMore: list.has_more, summary, error: null }),
      (error) => {
        if (!controller.signal.aborted) setState((current) => ({ key, runs: current?.runs ?? [], hasMore: false, summary: current?.summary ?? null, error: toApiError(error) }));
      },
    );
    return () => controller.abort();
  }, [workspaceId, days, key]);

  return {
    runs: state?.runs ?? [],
    hasMore: state?.hasMore ?? false,
    summary: state?.summary ?? null,
    error: state?.error ?? null,
    /** False while the current request is in flight (older data stays shown). */
    loaded: state?.key === key,
    everLoaded: state != null,
  };
}
