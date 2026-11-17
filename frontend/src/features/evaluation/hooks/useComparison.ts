import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { compareExperiments } from "../api/evaluation";
import { compareIdsParam } from "../lib/comparison";
import type { Comparison } from "../types";

interface ComparisonState {
  key: string;
  comparison: Comparison | null;
  error: ApiRequestError | null;
}

/** §30 comparison of 2–6 experiments; nothing is requested with fewer than two. */
export function useComparison(ids: readonly number[], baseline: number | null, metric: string | null) {
  const [state, setState] = useState<ComparisonState | null>(null);
  const [attempt, setAttempt] = useState(0);
  const idsParam = compareIdsParam(ids);
  const count = idsParam ? idsParam.split(",").length : 0;
  const key = `${idsParam}|${baseline ?? ""}|${metric ?? ""}|${attempt}`;

  useEffect(() => {
    if (count < 2) return;
    const controller = new AbortController();
    const wanted = idsParam.split(",").map(Number);
    compareExperiments({ ids: wanted, baseline, metric }, controller.signal).then(
      (comparison) => setState({ key, comparison, error: null }),
      (error) => {
        if (!controller.signal.aborted) setState((current) => ({ key, comparison: current?.comparison ?? null, error: toApiError(error) }));
      },
    );
    return () => controller.abort();
  }, [idsParam, count, baseline, metric, key]);

  const refresh = useCallback(() => setAttempt((value) => value + 1), []);

  const ready = count >= 2;
  return {
    comparison: ready ? (state?.comparison ?? null) : null,
    error: ready && state?.key === key ? state.error : null,
    loading: ready && state?.key !== key,
    refresh,
  };
}
