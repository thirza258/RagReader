import { API_BASE_URL, apiClient } from "../../../services/apiClient";
import { errorFromResponse, toApiError } from "../../../services/api/errors";
import { results, unwrap } from "../../../services/api/request";
import { postEventStream, SseHttpError } from "../../../services/streaming/sse";
import { authHeaders } from "../../auth/lib/session";
import { notifyUnauthorized } from "../../auth/lib/unauthorized";
import { parseChatStreamEvent } from "../lib/chatStream";
import type { ChatMessage, ChatStreamEvent, Conversation } from "../types";

/** Most recently updated first. */
export async function listConversations(workspaceId: number, signal?: AbortSignal): Promise<Conversation[]> {
  return results<Conversation>(await unwrap(apiClient.get("/conversations/", { params: { workspace_id: workspaceId }, signal })));
}

export function createConversation(input: { workspaceId: number; title?: string; documentIds?: number[] }): Promise<Conversation> {
  return unwrap(
    apiClient.post<Conversation>("/conversations/", {
      workspace_id: input.workspaceId,
      ...(input.title ? { title: input.title } : {}),
      ...(input.documentIds ? { document_ids: input.documentIds } : {}),
    }),
  );
}

export function updateConversation(id: number, patch: { title?: string; document_ids?: number[] }): Promise<Conversation> {
  return unwrap(apiClient.patch<Conversation>(`/conversations/${id}/`, patch));
}

export async function deleteConversation(id: number): Promise<void> {
  await unwrap(apiClient.delete(`/conversations/${id}/`));
}

/** Oldest first. */
export async function listMessages(conversationId: number, signal?: AbortSignal): Promise<ChatMessage[]> {
  return results<ChatMessage>(await unwrap(apiClient.get(`/conversations/${conversationId}/messages/`, { signal })));
}

/**
 * Asks a question and streams the answer (PRD §16). Resolves when the server
 * closes the stream. Errors found before streaming (empty question, no ready
 * documents, …) arrive as JSON and reject with an `ApiRequestError`.
 */
export async function streamMessage(
  conversationId: number,
  body: { content: string; document_ids?: number[] },
  options: { signal?: AbortSignal; onEvent: (event: ChatStreamEvent) => void },
): Promise<void> {
  try {
    await postEventStream({
      url: `${API_BASE_URL}/conversations/${conversationId}/messages/`,
      body,
      headers: authHeaders(),
      signal: options.signal,
      onEvent: (frame) => {
        const event = parseChatStreamEvent(frame);
        if (event) options.onEvent(event);
      },
    });
  } catch (error) {
    if (error instanceof SseHttpError) {
      if (error.status === 401) notifyUnauthorized();
      throw errorFromResponse(error.status, error.body, error.message);
    }
    throw toApiError(error);
  }
}
