import { loginPathFor } from "./redirect.ts";
import { clearToken } from "./session.ts";

/**
 * What happens when the workspace API answers 401: the stored token is
 * stale, so it is dropped and the user is sent to sign in, with the current
 * page as `next`. The router registers a handler so this stays an in-app
 * navigation; before it does, a full page load is the fallback.
 */

type Handler = (loginPath: string) => void;

let handler: Handler | null = null;
let redirecting = false;

export function setUnauthorizedHandler(next: Handler | null) {
  handler = next;
}

/** Paths (relative to `/api/v1`) that belong to the token-protected API. */
const PROTECTED = /^\/?(?:api\/v\d+\/)?(?:workspaces|documents|conversations)(?:\/|\?|$)/;

export function isWorkspaceApiPath(url: string | null | undefined): boolean {
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
