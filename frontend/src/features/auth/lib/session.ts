/**
 * The signed-in user as the browser remembers it. `username` and `email`
 * predate the workspace API; `token` is the bearer token sign-up now issues.
 * Storage access is guarded because private browsing modes can throw.
 */

const TOKEN_KEY = "token";
const USERNAME_KEY = "username";
const EMAIL_KEY = "email";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null | undefined) {
  try {
    if (value) window.localStorage.setItem(key, value);
    else window.localStorage.removeItem(key);
  } catch {
    // Storage unavailable: the session simply does not persist.
  }
}

export function getToken(): string | null {
  const token = read(TOKEN_KEY);
  return token && token !== "null" && token !== "undefined" ? token : null;
}

export function getUsername(): string | null {
  return read(USERNAME_KEY);
}

export function saveSession(session: { username?: string | null; email?: string | null; token?: string | null }) {
  if (session.username) write(USERNAME_KEY, session.username);
  if (session.email) write(EMAIL_KEY, session.email);
  write(TOKEN_KEY, session.token ?? null);
}

export function clearToken() {
  write(TOKEN_KEY, null);
}

/** `Authorization` header for fetch-based requests (axios adds it itself). */
export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
