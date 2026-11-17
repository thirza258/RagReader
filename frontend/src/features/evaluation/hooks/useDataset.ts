import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { getDataset, listDatasetItems } from "../api/evaluation";
import type { Dataset, DatasetItemsPage } from "../types";

interface DatasetState {
  key: string;
  dataset: Dataset | null;
  page: DatasetItemsPage | null;
  error: ApiRequestError | null;
}

/**
 * One dataset and the items of one of its versions (`version` null = the
 * latest). Every write creates a version, so callers `refresh()` afterwards.
 */
export function useDataset(datasetId: number | null, version: number | null) {
  const [state, setState] = useState<DatasetState | null>(null);
  const [attempt, setAttempt] = useState(0);
  const key = `${datasetId ?? ""}:${version ?? "latest"}:${attempt}`;

  useEffect(() => {
    if (datasetId == null) return;
    const controller = new AbortController();
    Promise.all([getDataset(datasetId, controller.signal), listDatasetItems(datasetId, version, controller.signal)]).then(
      ([dataset, page]) => setState({ key, dataset, page, error: null }),
      (error) => {
        if (!controller.signal.aborted) {
          setState((current) => ({ key, dataset: current?.dataset ?? null, page: current?.page ?? null, error: toApiError(error) }));
        }
      },
    );
    return () => controller.abort();
  }, [datasetId, version, key]);

  const refresh = useCallback(() => setAttempt((value) => value + 1), []);

  const current = state && state.dataset?.id === datasetId ? state : state?.key === key ? state : null;
  return {
    dataset: current?.dataset ?? null,
    items: current?.page?.results ?? [],
    /** The version whose items are shown. */
    version: current?.page?.version ?? null,
    error: state?.key === key ? state.error : null,
    loaded: state?.key === key,
    refresh,
  };
}
