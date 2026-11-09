import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { createWorkspace, deleteWorkspace, listWorkspaces, renameWorkspace } from "../api/workspaces";
import type { Workspace } from "../types";

interface WorkspacesState {
  list: Workspace[];
  loaded: boolean;
  error: ApiRequestError | null;
}

/** The user's workspaces plus create / rename / delete. */
export function useWorkspaces() {
  const [state, setState] = useState<WorkspacesState>({ list: [], loaded: false, error: null });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listWorkspaces(controller.signal).then(
      (list) => setState({ list, loaded: true, error: null }),
      (error) => {
        if (!controller.signal.aborted) setState((current) => ({ ...current, loaded: true, error: toApiError(error) }));
      },
    );
    return () => controller.abort();
  }, [version]);

  const refresh = useCallback(() => setVersion((value) => value + 1), []);

  const create = useCallback(async (name: string) => {
    const workspace = await createWorkspace(name);
    setState((current) => ({ ...current, list: [...current.list.filter((item) => item.id !== workspace.id), workspace] }));
    return workspace;
  }, []);

  const rename = useCallback(async (id: number, name: string) => {
    const workspace = await renameWorkspace(id, name);
    setState((current) => ({ ...current, list: current.list.map((item) => (item.id === id ? workspace : item)) }));
    return workspace;
  }, []);

  const remove = useCallback(async (id: number) => {
    await deleteWorkspace(id);
    setState((current) => ({ ...current, list: current.list.filter((item) => item.id !== id) }));
  }, []);

  return { ...state, refresh, create, rename, remove };
}
