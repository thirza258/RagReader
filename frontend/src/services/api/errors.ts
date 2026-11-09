/**
 * One error shape for every failed request to the workspace API.
 *
 * The API answers non-2xx requests with
 * `{"error": {"code", "message", "retryable", "stage", "details"}}`; legacy
 * endpoints use `{"message"}` or `{"error": "text"}`; network failures have no
 * body at all. `toApiError` folds all of them into `ApiRequestError` so the
 * UI can always show a code, a message and whether retrying makes sense.
 *
 * No imports: axios errors are recognised by shape, so tests can load this.
 */

export interface ApiErrorInit {
  status: number | null;
  code: string;
  message: string;
  retryable?: boolean;
  stage?: string | null;
  details?: unknown;
  body?: unknown;
}

export class ApiRequestError extends Error {
  status: number | null;
  code: string;
  retryable: boolean;
  stage: string | null;
  details: unknown;
  /** The parsed response body, e.g. a document returned with a 503. */
  body: unknown;

  constructor(init: ApiErrorInit) {
    super(init.message);
    this.name = "ApiRequestError";
    this.status = init.status;
    this.code = init.code;
    this.retryable = init.retryable ?? false;
    this.stage = init.stage ?? null;
    this.details = init.details ?? null;
    this.body = init.body ?? null;
  }
}

const STATUS_CODES: Record<number, string> = {
  400: "invalid_request",
  401: "authentication_required",
  403: "forbidden",
  404: "not_found",
  409: "conflict",
  413: "file_too_large",
  415: "unsupported_file_type",
  429: "rate_limited",
  500: "server_error",
  502: "bad_gateway",
  503: "service_unavailable",
  504: "gateway_timeout",
};

const STATUS_MESSAGES: Record<number, string> = {
  401: "Your session has expired. Sign in again to continue.",
  404: "That item no longer exists.",
  413: "The file is larger than the upload limit.",
  502: "The server is not reachable right now. Try again in a moment.",
  503: "The service is temporarily unavailable. Try again in a moment.",
  504: "The server took too long to answer. Try again.",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Builds the error for an HTTP response whose status is not 2xx. */
export function errorFromResponse(status: number | null, body: unknown, fallback = "The request failed."): ApiRequestError {
  const retryableStatus = status === null || status === 429 || status >= 500;
  if (isRecord(body) && isRecord(body.error)) {
    const envelope = body.error;
    return new ApiRequestError({
      status,
      code: typeof envelope.code === "string" && envelope.code ? envelope.code : STATUS_CODES[status ?? 0] ?? "request_failed",
      message: typeof envelope.message === "string" && envelope.message ? envelope.message : STATUS_MESSAGES[status ?? 0] ?? fallback,
      retryable: typeof envelope.retryable === "boolean" ? envelope.retryable : retryableStatus,
      stage: typeof envelope.stage === "string" ? envelope.stage : null,
      details: envelope.details ?? null,
      body,
    });
  }
  let message = "";
  if (isRecord(body)) {
    if (typeof body.message === "string") message = body.message;
    else if (typeof body.error === "string") message = body.error;
    else if (typeof body.detail === "string") message = body.detail;
  }
  return new ApiRequestError({
    status,
    code: STATUS_CODES[status ?? 0] ?? "request_failed",
    message: message || STATUS_MESSAGES[status ?? 0] || fallback,
    retryable: retryableStatus,
    body,
  });
}

/** True for a request the caller cancelled (AbortController or axios cancel). */
export function isAbortError(error: unknown): boolean {
  if (!isRecord(error) && !(error instanceof Error)) return false;
  const candidate = error as { name?: unknown; code?: unknown };
  return candidate.name === "AbortError" || candidate.name === "CanceledError" || candidate.code === "ERR_CANCELED";
}

/** Normalises anything thrown by axios, fetch or our own code. */
export function toApiError(error: unknown, fallback = "Something went wrong. Try again."): ApiRequestError {
  if (error instanceof ApiRequestError) return error;
  if (isAbortError(error)) {
    return new ApiRequestError({ status: null, code: "aborted", message: "The request was cancelled.", retryable: true });
  }
  const axiosLike = error as { response?: { status?: number; data?: unknown }; message?: string; code?: string } | null;
  if (axiosLike && isRecord(axiosLike) && isRecord(axiosLike.response)) {
    const status = typeof axiosLike.response.status === "number" ? axiosLike.response.status : null;
    return errorFromResponse(status, axiosLike.response.data, fallback);
  }
  if (axiosLike && (axiosLike.code === "ECONNABORTED" || axiosLike.code === "ETIMEDOUT")) {
    return new ApiRequestError({ status: null, code: "timeout", message: "The server took too long to answer. Try again.", retryable: true });
  }
  if (axiosLike && (axiosLike.code === "ERR_NETWORK" || (error instanceof TypeError && /fetch|network/i.test(error.message)))) {
    return new ApiRequestError({
      status: null,
      code: "network_error",
      message: "Could not reach the server. Check your connection and try again.",
      retryable: true,
    });
  }
  const message = error instanceof Error && error.message ? error.message : fallback;
  return new ApiRequestError({ status: null, code: "unexpected_error", message, retryable: true });
}
