/**
 * Where the login page may send the user afterwards.
 *
 * `next` comes from the query string, so anyone can craft it. Only a path on
 * this site is accepted: it must start with "/" but not "//" or "/\" (both are
 * protocol-relative URLs to a browser), may not contain control characters
 * (the URL parser drops tabs and newlines, turning "/\t/evil" into "//evil"),
 * and must still resolve to this origin.
 */

const PROBE_ORIGIN = "http://ragreader.invalid";

export function sanitizeNextPath(next: string | null | undefined): string | null {
  if (typeof next !== "string" || next.length === 0 || next.length > 2048) return null;
  if (!next.startsWith("/")) return null;
  if (next.startsWith("//") || next.startsWith("/\\")) return null;
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(next)) return null;
  try {
    const resolved = new URL(next, PROBE_ORIGIN);
    if (resolved.origin !== PROBE_ORIGIN) return null;
  } catch {
    return null;
  }
  return next;
}

/** `/login?next=<path>` for a path on this site; plain `/login` otherwise. */
export function loginPathFor(currentPath: string | null | undefined): string {
  const safe = sanitizeNextPath(currentPath);
  if (!safe || safe === "/login" || safe.startsWith("/login?") || safe.startsWith("/login/")) return "/login";
  return `/login?next=${encodeURIComponent(safe)}`;
}
