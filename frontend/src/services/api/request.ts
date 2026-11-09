import type { AxiosResponse } from "axios";
import { ApiRequestError, errorFromResponse, toApiError } from "./errors";

/** Resolves to the response body, or rejects with an `ApiRequestError`. */
export async function unwrap<T>(request: Promise<AxiosResponse<T>>): Promise<T> {
  try {
    return (await request).data;
  } catch (error) {
    throw await toApiErrorReadingBlob(error);
  }
}

/**
 * Like `toApiError`, but also reads an error body that arrived as a Blob
 * (requests made with `responseType: "blob"` receive JSON errors that way).
 */
export async function toApiErrorReadingBlob(error: unknown): Promise<ApiRequestError> {
  const response = (error as { response?: { status?: number; data?: unknown } } | null)?.response;
  if (response && typeof Blob !== "undefined" && response.data instanceof Blob) {
    let body: unknown;
    try {
      const text = await response.data.text();
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    } catch {
      body = null;
    }
    return errorFromResponse(typeof response.status === "number" ? response.status : null, body);
  }
  return toApiError(error);
}

/** `{"results": [...]}` lists; anything else is treated as empty. */
export function results<T>(body: unknown): T[] {
  const list = (body as { results?: unknown } | null)?.results;
  return Array.isArray(list) ? (list as T[]) : [];
}
