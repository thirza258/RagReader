import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { listExperiments } from "../api/evaluation";
import { isActive } from "../lib/experiments";
import type { Experiment } from "../types";

/** The registry is re-read this often while an experiment is queued or running. */
export const LIST_POLL_MS = 4000;

interface ExperimentsState {
  key: string;
  list: Experiment[];
  error: ApiRequestError | null;
}

/**
 * The workspace's experiments, newest first (PRD §29). While any is queued
 * or running the list is re-read every 4 s; `refreshKey` and `refresh()`
 * re-read it at once. Unmounting stops the polling.
 */
export function useExperiments(workspaceId: number, refreshKey = 0) {
  const [state, setState] = useState<ExperimentsState | null>(null);
  const [version, setVersion] = useState(0);
  const key = `${workspaceId}:${refreshKey}:${version}`;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;

    async function load() {
      controller = new AbortController();
      try {
        const list = await listExperiments({ workspaceId }, controller.signal);
        if (cancelled) return;
        setState({ key, list, error: null });
        if (list.some((experiment) => isActive(experiment.status))) timer = setTimeout(load, LIST_POLL_MS);
      } catch (error) {
        if (cancelled) return;
        setState((current) => ({ key, list: current?.list ?? [], error: toApiError(error) }));
      }
    }

    void load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller?.abort();
    };
  }, [workspaceId, key]);

  const refresh = useCallback(() => setVersion((value) => value + 1), []);

  return {
    list: state?.list ?? [],
    error: state?.error ?? null,
    loaded: state?.key === key,
    everLoaded: state != null,
    refresh,
  };
}

export type ExperimentsApi = ReturnType<typeof useExperiments>;
