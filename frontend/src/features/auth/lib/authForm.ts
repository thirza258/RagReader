/**
 * The sign-in / create-account form's rules: what it checks before sending,
 * and what it shows for each server answer. No imports, so tests can load it.
 *
 * Server codes: `invalid_credentials` (401, unknown account or wrong password
 * alike), `password_not_set` (409, an account from before passwords),
 * `account_exists` (409), `invalid_request` (400, field errors in `details`,
 * including the password validators' messages) and `rate_limited` (429).
 */

export type AuthMode = "signin" | "create";
export type AuthField = "identifier" | "username" | "email" | "password" | "confirm";
export type FieldErrors = Partial<Record<AuthField, string[]>>;

export interface AuthValues {
  identifier: string;
  username: string;
  email: string;
  password: string;
  confirm: string;
}

export interface AuthErrorLike {
  status: number | null;
  code: string;
  message: string;
  details?: unknown;
}

export interface AuthFeedback {
  /** The mode to show; differs from the current one when the error calls for it. */
  mode: AuthMode;
  formError: string;
  /** Not an error: an explanation shown above the form. */
  notice: string;
  fieldErrors: FieldErrors;
  /** Offer a one-click switch to this mode. */
  suggestMode: AuthMode | null;
}

export const PASSWORD_NOT_SET_NOTICE =
  "This account was created before passwords existed. Enter its exact username and email, " +
  "then choose a password to keep using it.";

const RATE_LIMITED_FALLBACK = "Too many attempts. Wait a minute and try again.";

/** Problems the form can find without asking the server. */
export function validateAuthForm(mode: AuthMode, values: AuthValues): FieldErrors {
  const errors: FieldErrors = {};
  if (mode === "signin") {
    if (!values.identifier.trim()) errors.identifier = ["Enter your username or email."];
    if (!values.password) errors.password = ["Enter your password."];
    return errors;
  }
  if (!values.username.trim()) errors.username = ["Choose a username."];
  if (!values.email.trim()) errors.email = ["Enter your email."];
  if (!values.password) errors.password = ["Choose a password."];
  else if (values.confirm !== values.password) errors.confirm = ["The passwords do not match."];
  return errors;
}

function fieldErrorsFrom(details: unknown, mode: AuthMode): FieldErrors {
  if (typeof details !== "object" || details === null || Array.isArray(details)) return {};
  const fields: Record<string, AuthField> = mode === "signin"
    ? { USERNAME: "identifier", EMAIL: "identifier", PASSWORD: "password" }
    : { USERNAME: "username", EMAIL: "email", PASSWORD: "password" };
  const errors: FieldErrors = {};
  for (const [key, value] of Object.entries(details as Record<string, unknown>)) {
    const field = fields[key];
    if (!field) continue;
    const messages = (Array.isArray(value) ? value : [value]).filter((m): m is string => typeof m === "string" && m.length > 0);
    if (messages.length) errors[field] = [...(errors[field] ?? []), ...messages];
  }
  return errors;
}

export function authFeedback(error: AuthErrorLike, mode: AuthMode): AuthFeedback {
  const base: AuthFeedback = { mode, formError: "", notice: "", fieldErrors: {}, suggestMode: null };
  if (error.code === "password_not_set") {
    return { ...base, mode: "create", notice: PASSWORD_NOT_SET_NOTICE };
  }
  if (error.code === "account_exists") {
    return { ...base, formError: error.message, suggestMode: "signin" };
  }
  if (error.code === "invalid_credentials") {
    return { ...base, formError: error.message || "The username, email or password is incorrect." };
  }
  if (error.status === 429 || error.code === "rate_limited") {
    return { ...base, formError: error.message && error.code === "rate_limited" ? error.message : RATE_LIMITED_FALLBACK };
  }
  if (error.code === "invalid_request") {
    const fieldErrors = fieldErrorsFrom(error.details, mode);
    return { ...base, fieldErrors, formError: Object.keys(fieldErrors).length ? "" : error.message };
  }
  return { ...base, formError: error.message || "Something went wrong. Try again." };
}

/** Carry what was typed across a mode switch. */
export function carryOver(values: AuthValues, to: AuthMode): AuthValues {
  if (to === "create") {
    const typed = values.identifier.trim();
    if (!typed) return values;
    return typed.includes("@")
      ? { ...values, email: values.email || typed }
      : { ...values, username: values.username || typed };
  }
  return { ...values, identifier: values.identifier || values.username || values.email };
}
