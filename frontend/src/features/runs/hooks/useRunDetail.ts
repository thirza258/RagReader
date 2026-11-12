import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { getRun } from "../api/runs";
import type { RetrievalRunDetail } from "../types";

/** Runs never change once recorded, so a loaded trace is kept for the session. */
const CACHE_LIMIT = 50;
const cache = new Map<number, RetrievalRunDetail>();

function remember(run: RetrievalRunDetail) {
  cache.delete(run.id);
  cache.set(run.id, run);
  while (cache.size > CACHE_LIMIT) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    cache.delete(oldest);
  }
}

interface Loaded {
  id: number;
  run: RetrievalRunDetail | null;
  error: ApiRequestError | null;
}

/**
 * One run's full trace. Pass null until it is needed (the Why panel passes
 * the id only once it is opened), so a long thread does not fetch a trace
 * per answer. Aborts on unmount or when the id changes.
 */
export function useRunDetail(runId: number | null) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [attempt, setAttempt] = useState(0);
  const cached = runId != null ? (cache.get(runId) ?? null) : null;

  useEffect(() => {
    if (runId == null || cache.has(runId)) return;
    const controller = new AbortController();
    getRun(runId, controller.signal).then(
      (run) => {
        remember(run);
        setLoaded({ id: runId, run, error: null });
      },
      (error) => {
        if (!controller.signal.aborted) setLoaded({ id: runId, run: null, error: toApiError(error) });
      },
    );
    return () => controller.abort();
  }, [runId, attempt]);

  const retry = useCallback(() => {
    setLoaded(null);
    setAttempt((value) => value + 1);
  }, []);

  const current = loaded && loaded.id === runId ? loaded : null;
  return {
    run: cached ?? current?.run ?? null,
    error: cached ? null : (current?.error ?? null),
    loading: runId != null && !cached && !current,
    retry,
  };
}
