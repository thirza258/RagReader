/**
 * The analysis WebSocket authenticates in-band: the first frame the client
 * sends is `{"type": "auth", "token": "rr_…"}`, so the token never appears in
 * a URL or an access log. The server closes with 4401 when that frame is
 * missing or the token is invalid, and with 4404 (after a `job_not_found`
 * error frame) for a batch that does not exist or is someone else's. Neither
 * is worth retrying: only signing in (again) can fix them.
 *
 * No imports, so tests can load it.
 */

export const CLOSE_UNAUTHENTICATED = 4401;
export const CLOSE_NOT_FOUND = 4404;

export type SocketAuthFailure = "unauthenticated" | "not_found";
export type SocketCloseKind = SocketAuthFailure | "finished" | "retry";

export function authFrame(token: string): string {
  return JSON.stringify({ type: "auth", token });
}

/** What to do after the socket closed with `code`. */
export function classifySocketClose(code: number, completed: boolean): SocketCloseKind {
  if (code === CLOSE_UNAUTHENTICATED) return "unauthenticated";
  if (code === CLOSE_NOT_FOUND) return "not_found";
  if (completed || code === 1000) return "finished";
  return "retry";
}

/** The terminal frame the server sends before closing with 4404. */
export function isBatchNotFoundFrame(message: { error_code?: unknown; method?: unknown } | null | undefined): boolean {
  return Boolean(message) && message?.error_code === "job_not_found" && !message?.method;
}

/** The sign-in prompt shown for each failure. */
export function socketAuthMessage(kind: SocketAuthFailure): string {
  return kind === "unauthenticated"
    ? "Your session has expired or is no longer valid. Sign in again to follow this analysis."
    : "This analysis was not found for your account. Sign in with the account that started it, or start a new analysis.";
}
