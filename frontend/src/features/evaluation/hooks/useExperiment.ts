import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { getExperiment, listExperimentItems } from "../api/evaluation";
import { POLL_MS, isActive } from "../lib/experiments";
import type { ExperimentDetail, ExperimentItemsPage, ExperimentItemsQuery } from "../types";

interface ExperimentState {
  id: number;
  experiment: ExperimentDetail | null;
  error: ApiRequestError | null;
}

/**
 * One experiment with live progress: re-read every 2 s while it is queued
 * or running (PRD §29), stopped when it finishes, the id changes or the
 * view unmounts. `refresh()` re-reads it and restarts polling, e.g. after
 * start, resume or cancel.
 */
export function useExperiment(id: number | null) {
  const [state, setState] = useState<ExperimentState | null>(null);
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
        const experiment = await getExperiment(id as number, controller.signal);
        if (cancelled) return;
        failures = 0;
        live = isActive(experiment.status);
        setState({ id: id as number, experiment, error: null });
        if (live) timer = setTimeout(load, POLL_MS);
      } catch (error) {
        if (cancelled) return;
        const apiError = toApiError(error);
        failures += 1;
        setState((current) => ({ id: id as number, experiment: current?.id === id ? current.experiment : null, error: apiError }));
        // A blip while a run is live: try again, backing off; gone or signed out: stop.
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
  return {
    experiment: current?.experiment ?? null,
    error: current?.error ?? null,
    loading: id != null && current == null,
    refresh,
  };
}

interface ItemsState {
  key: string;
  page: ExperimentItemsPage | null;
  error: ApiRequestError | null;
}

/**
 * A page of an experiment's items with optional status and failure filters.
 * `progressKey` (e.g. the processed count) re-reads it as a run advances.
 */
export function useExperimentItems(id: number | null, query: ExperimentItemsQuery, progressKey: string | number = 0) {
  const [state, setState] = useState<ItemsState | null>(null);
  const [attempt, setAttempt] = useState(0);
  const { status = null, category = null, label = null, offset = 0, limit = 100 } = query;
  const key = `${id ?? ""}:${status ?? ""}:${category ?? ""}:${label ?? ""}:${offset}:${limit}:${progressKey}:${attempt}`;

  useEffect(() => {
    if (id == null) return;
    const controller = new AbortController();
    listExperimentItems(id, { status, category, label, offset, limit }, controller.signal).then(
      (page) => setState({ key, page, error: null }),
      (error) => {
        if (!controller.signal.aborted) setState((current) => ({ key, page: current?.page ?? null, error: toApiError(error) }));
      },
    );
    return () => controller.abort();
  }, [id, status, category, label, offset, limit, key]);

  const refresh = useCallback(() => setAttempt((value) => value + 1), []);

  return {
    items: state?.page?.results ?? [],
    count: state?.page?.count ?? 0,
    offset: state?.page?.offset ?? offset,
    limit: state?.page?.limit ?? limit,
    error: state?.key === key ? state.error : null,
    loaded: state?.key === key,
    everLoaded: state != null,
    refresh,
  };
}
