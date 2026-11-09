import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { createConversation, deleteConversation, listConversations, updateConversation } from "../api/conversations";
import type { Conversation } from "../types";

interface ConversationsState {
  list: Conversation[];
  loaded: boolean;
  error: ApiRequestError | null;
}

function byUpdatedDesc(a: Conversation, b: Conversation): number {
  return (b.updated_at || "").localeCompare(a.updated_at || "");
}

/** A workspace's conversations (PRD §15): list, create, rename, delete, rescope. */
export function useConversations(workspaceId: number) {
  const [state, setState] = useState<ConversationsState>({ list: [], loaded: false, error: null });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listConversations(workspaceId, controller.signal).then(
      (list) => setState({ list, loaded: true, error: null }),
      (error) => {
        if (!controller.signal.aborted) setState((current) => ({ ...current, loaded: true, error: toApiError(error) }));
      },
    );
    return () => controller.abort();
  }, [workspaceId, version]);

  const refresh = useCallback(() => setVersion((value) => value + 1), []);

  const store = useCallback((conversation: Conversation) => {
    setState((current) => ({
      ...current,
      list: [conversation, ...current.list.filter((item) => item.id !== conversation.id)].sort(byUpdatedDesc),
    }));
  }, []);

  const create = useCallback(
    async (documentIds: number[], title?: string) => {
      const conversation = await createConversation({ workspaceId, documentIds, title });
      store(conversation);
      return conversation;
    },
    [workspaceId, store],
  );

  const update = useCallback(
    async (id: number, patch: { title?: string; document_ids?: number[] }) => {
      const conversation = await updateConversation(id, patch);
      store(conversation);
      return conversation;
    },
    [store],
  );

  /** Shows the new scope at once; restores `previousIds` if the PATCH fails. */
  const setScope = useCallback(
    async (id: number, documentIds: number[], previousIds: number[]) => {
      const withScope = (ids: number[]) => (current: ConversationsState) => ({
        ...current,
        list: current.list.map((item) => (item.id === id ? { ...item, document_ids: ids } : item)),
      });
      setState(withScope(documentIds));
      try {
        return await update(id, { document_ids: documentIds });
      } catch (error) {
        setState(withScope(previousIds));
        throw toApiError(error);
      }
    },
    [update],
  );

  const remove = useCallback(async (id: number) => {
    await deleteConversation(id);
    setState((current) => ({ ...current, list: current.list.filter((item) => item.id !== id) }));
  }, []);

  return { ...state, refresh, create, update, setScope, remove };
}
