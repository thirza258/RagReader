import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { createPipeline, deletePipeline, getPipelineOptions, listPipelines, updatePipeline } from "../api/pipelines";
import type { Pipeline, PipelineConfig, PipelineOptions } from "../types";

interface PipelinesState {
  key: number;
  list: Pipeline[];
  options: PipelineOptions | null;
  error: ApiRequestError | null;
}

/**
 * A workspace's pipelines and the form options (PRD §17), read together.
 * Edits update the list in place; `refresh` re-reads it.
 */
export function usePipelines(workspaceId: number) {
  const [state, setState] = useState<PipelinesState | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([listPipelines(workspaceId, controller.signal), getPipelineOptions(controller.signal)]).then(
      ([list, options]) => setState({ key: workspaceId, list, options, error: null }),
      (error) => {
        if (!controller.signal.aborted) setState((current) => ({ key: workspaceId, list: current?.list ?? [], options: current?.options ?? null, error: toApiError(error) }));
      },
    );
    return () => controller.abort();
  }, [workspaceId, version]);

  const refresh = useCallback(() => setVersion((value) => value + 1), []);

  const store = useCallback((pipeline: Pipeline) => {
    setState((current) =>
      current
        ? {
            ...current,
            list: current.list.some((item) => item.id === pipeline.id)
              ? current.list.map((item) => (item.id === pipeline.id ? pipeline : item))
              : [...current.list, pipeline],
          }
        : current,
    );
  }, []);

  const create = useCallback(
    async (name: string, config: Partial<PipelineConfig>) => {
      const pipeline = await createPipeline({ workspaceId, name, config });
      store(pipeline);
      return pipeline;
    },
    [workspaceId, store],
  );

  const update = useCallback(
    async (id: number, patch: { name?: string; config?: Partial<PipelineConfig> }) => {
      const pipeline = await updatePipeline(id, patch);
      store(pipeline);
      return pipeline;
    },
    [store],
  );

  const remove = useCallback(async (id: number) => {
    await deletePipeline(id);
    setState((current) => (current ? { ...current, list: current.list.filter((item) => item.id !== id) } : current));
  }, []);

  const current = state?.key === workspaceId ? state : null;
  return {
    list: current?.list ?? [],
    options: current?.options ?? null,
    error: current?.error ?? null,
    loaded: current != null,
    refresh,
    create,
    update,
    remove,
  };
}

export type PipelinesApi = ReturnType<typeof usePipelines>;
