import type { WorkspaceDocument } from "../types/index.ts";

/**
 * The documents a conversation scope covers. `document_ids` empty means every
 * READY document in the workspace at question time.
 */
export function includedIds(scopeIds: readonly number[], documents: readonly Pick<WorkspaceDocument, "id" | "status">[]): Set<number> {
  if (scopeIds.length === 0) return new Set(documents.filter((document) => document.status === "READY").map((document) => document.id));
  return new Set(scopeIds);
}
