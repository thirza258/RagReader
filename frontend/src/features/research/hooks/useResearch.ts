import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { getResearchTask, listResearchTasks } from "../api/research";
import { POLL_MS, isActive } from "../lib/research";
import type { ResearchTask } from "../types";

interface ListState {
  key: string;
  list: ResearchTask[];
  error: ApiRequestError | null;
}

/** The workspace's research tasks, newest first; re-read while any is queued or running. */
export function useResearchTasks(workspaceId: number) {
  const [state, setState] = useState<ListState | null>(null);
  const [version, setVersion] = useState(0);
  const key = `${workspaceId}:${version}`;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;

    async function load() {
      controller = new AbortController();
      try {
        const list = await listResearchTasks(workspaceId, controller.signal);
        if (cancelled) return;
        setState({ key, list, error: null });
        if (list.some((task) => isActive(task.status))) timer = setTimeout(load, POLL_MS);
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
  return { list: state?.list ?? [], error: state?.error ?? null, loaded: state != null, refresh };
}

interface TaskState {
  id: number;
  task: ResearchTask | null;
  error: ApiRequestError | null;
}

/** One task with its result; re-read every 2.5 s while it is queued or running. */
export function useResearchTask(id: number | null) {
  const [state, setState] = useState<TaskState | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (id == null) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;
    let failures = 0;
    let live = false;

    async function load() {
      controller = new AbortController();
      try {
        const task = await getResearchTask(id as number, controller.signal);
        if (cancelled) return;
        failures = 0;
        live = isActive(task.status);
        setState({ id: id as number, task, error: null });
        if (live) timer = setTimeout(load, POLL_MS);
      } catch (error) {
        if (cancelled) return;
        const apiError = toApiError(error);
        failures += 1;
        setState((current) => ({ id: id as number, task: current?.id === id ? current.task : null, error: apiError }));
        if (live && apiError.status !== 401 && apiError.status !== 404 && failures < 6) {
          timer = setTimeout(load, POLL_MS * 2 ** Math.min(failures, 4));
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller?.abort();
    };
  }, [id, attempt]);

  const refresh = useCallback(() => setAttempt((value) => value + 1), []);
  const current = state && state.id === id ? state : null;
  return { task: current?.task ?? null, error: current?.error ?? null, loading: id != null && current == null, refresh };
}
