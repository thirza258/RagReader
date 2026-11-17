import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { listDatasets } from "../api/evaluation";
import type { Dataset } from "../types";

interface DatasetsState {
  key: string;
  list: Dataset[];
  error: ApiRequestError | null;
}

/**
 * A workspace's evaluation datasets, most recently updated first.
 * `refreshKey` (e.g. bumped after "Add to dataset") and `refresh()` re-read
 * the list; `store`/`removeLocal` apply a server response at once.
 */
export function useDatasets(workspaceId: number, refreshKey = 0) {
  const [state, setState] = useState<DatasetsState | null>(null);
  const [version, setVersion] = useState(0);
  const key = `${workspaceId}:${refreshKey}:${version}`;

  useEffect(() => {
    const controller = new AbortController();
    listDatasets(workspaceId, controller.signal).then(
      (list) => setState({ key, list, error: null }),
      (error) => {
        if (!controller.signal.aborted) setState((current) => ({ key, list: current?.list ?? [], error: toApiError(error) }));
      },
    );
    return () => controller.abort();
  }, [workspaceId, key]);

  const refresh = useCallback(() => setVersion((value) => value + 1), []);

  const store = useCallback((dataset: Dataset) => {
    setState((current) => (current ? { ...current, list: [dataset, ...current.list.filter((item) => item.id !== dataset.id)] } : current));
  }, []);

  const removeLocal = useCallback((id: number) => {
    setState((current) => (current ? { ...current, list: current.list.filter((item) => item.id !== id) } : current));
  }, []);

  return {
    list: state?.list ?? [],
    error: state?.error ?? null,
    /** False while the current request is in flight (older data stays shown). */
    loaded: state?.key === key,
    everLoaded: state != null,
    refresh,
    store,
    removeLocal,
  };
}

export type DatasetsApi = ReturnType<typeof useDatasets>;
