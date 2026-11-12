import { loginPathFor } from "./redirect.ts";
import { clearToken } from "./session.ts";

/**
 * What happens when a token-protected endpoint answers 401: the stored token
 * is stale, so it is dropped and the user is sent to sign in, with the
 * current page as `next`. The router registers a handler so this stays an
 * in-app navigation; before it does, a full page load is the fallback.
 */

type Handler = (loginPath: string) => void;

let handler: Handler | null = null;
let redirecting = false;

export function setUnauthorizedHandler(next: Handler | null) {
  handler = next;
}

/**
 * Paths (relative to `/api/v1`) that need the bearer token: the workspace API
 * and every legacy and deep-analysis endpoint. Left out on purpose:
 * `sign-in`/`sign-up` (a 401 there means a wrong password, not a stale
 * session), `sign-out` (the session is ending anyway) and the public
 * `analysis-config`.
 */
const PROTECTED = new RegExp(
  "^/?(?:api/v\\d+/)?(?:" +
    [
      "workspaces", "documents", "conversations", "retrieval",
      "insert-data", "insert-text", "insert-url", "open-chat", "job-status", "query",
      "start-analysis", "analysis-status", "document", "conversation-history", "conversation",
      "chunk", "ground-truth-chunk", "ground-truth-response", "evaluate",
    ].join("|") +
    ")(?:/|\\?|$)",
);

export function isProtectedApiPath(url: string | null | undefined): boolean {
  if (!url) return false;
  let path = url;
  if (/^https?:\/\//i.test(path)) {
    try {
      path = new URL(path).pathname;
    } catch {
      return false;
    }
  }
  return PROTECTED.test(path);
}

export function notifyUnauthorized() {
  clearToken();
  if (typeof window === "undefined") return;
  const { pathname, search } = window.location;
  if (pathname === "/login" || redirecting) return;
  redirecting = true;
  window.setTimeout(() => {
    redirecting = false;
  }, 1500);
  const target = loginPathFor(`${pathname}${search}`);
  if (handler) handler(target);
  else window.location.assign(target);
}
