/** Reuse an intent's UUID across remounts and reloads until a new Run action. */
const pending = new Map<string, string>();

function generateUUID(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function analysisRequestId(conversationId: string, intent = "initial"): string {
  const key = `analysis_request_${conversationId}_${intent}`;
  let saved: string | null = null;
  try { saved = sessionStorage.getItem(key); } catch { /* Storage can be disabled. */ }
  const id = saved || pending.get(key) || generateUUID();
  pending.set(key, id);
  try { sessionStorage.setItem(key, id); } catch { /* Remounts still share the in-memory id. */ }
  return id;
}

export function analysisFailureSummary(failed: number, total: number): string {
  if (!failed) return "";
  return `${failed} of ${total} variants failed. See the errors below. Run Deep Analysis again to retry.`;
}
