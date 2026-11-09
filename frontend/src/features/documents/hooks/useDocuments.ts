import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { listDocuments } from "../api/documents";
import { isTerminalStatus } from "../lib/ingestionStages";
import type { WorkspaceDocument } from "../types";

/** Poll interval while a document is still being ingested (PRD §9). */
export const DOCUMENT_POLL_MS = 2000;
const HIDDEN_POLL_MS = 10000;
const MAX_BACKOFF_MS = 30000;

export function pollBackoff(failures: number): number {
  return Math.min(MAX_BACKOFF_MS, DOCUMENT_POLL_MS * 2 ** Math.max(0, failures - 1));
}

interface DocumentsState {
  documents: WorkspaceDocument[];
  loaded: boolean;
  error: ApiRequestError | null;
  /** "“Paper” is ready." when a document finished since the last read, for a live region. */
  announcement: string;
}

/** Documents that became READY or FAILED between two reads of the list. */
export function finishedSince(previous: readonly WorkspaceDocument[], next: readonly WorkspaceDocument[]): string {
  const before = new Map(previous.map((document) => [document.id, document.status]));
  const lines: string[] = [];
  for (const document of next) {
    const old = before.get(document.id);
    if (old === undefined || old === document.status) continue;
    if (document.status === "READY") lines.push(`“${document.title}” is ready.`);
    else if (document.status === "FAILED") lines.push(`“${document.title}” failed to ingest.`);
  }
  return lines.join(" ");
}

/**
 * The workspace's documents. While any document is not READY or FAILED the
 * list is re-read every 2 s (10 s when the tab is hidden); failures back off
 * up to 30 s. Polling stops when everything is terminal and resumes after
 * `refresh()`, e.g. after an upload or a retry. Unmounting stops it.
 */
export function useDocuments(workspaceId: number) {
  const [state, setState] = useState<DocumentsState>({ documents: [], loaded: false, error: null, announcement: "" });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;
    let failures = 0;

    const schedule = (delay: number) => {
      if (!cancelled) timer = setTimeout(load, delay);
    };

    async function load() {
      controller = new AbortController();
      try {
        const documents = await listDocuments(workspaceId, controller.signal);
        if (cancelled) return;
        failures = 0;
        setState((current) => ({
          documents,
          loaded: true,
          error: null,
          announcement: finishedSince(current.documents, documents) || current.announcement,
        }));
        if (documents.some((item) => !isTerminalStatus(item.status))) {
          schedule(typeof window !== "undefined" && window.document.hidden ? HIDDEN_POLL_MS : DOCUMENT_POLL_MS);
        }
      } catch (error) {
        if (cancelled) return;
        const apiError = toApiError(error);
        failures += 1;
        setState((current) => ({ ...current, loaded: true, error: apiError }));
        // Signed out or gone: polling again cannot help.
        if (apiError.status === 401 || apiError.status === 403 || apiError.status === 404) return;
        schedule(pollBackoff(failures));
      }
    }

    void load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller?.abort();
    };
  }, [workspaceId, version]);

  /** Re-read now (and resume polling if something is in progress). */
  const refresh = useCallback(() => setVersion((value) => value + 1), []);

  /** Apply a server response locally, then re-read to stay in step. */
  const upsert = useCallback((document: WorkspaceDocument) => {
    setState((current) => {
      const exists = current.documents.some((item) => item.id === document.id);
      return {
        ...current,
        documents: exists ? current.documents.map((item) => (item.id === document.id ? document : item)) : [document, ...current.documents],
      };
    });
    setVersion((value) => value + 1);
  }, []);

  const removeLocal = useCallback((id: number) => {
    setState((current) => ({ ...current, documents: current.documents.filter((item) => item.id !== id) }));
    setVersion((value) => value + 1);
  }, []);

  return { ...state, refresh, upsert, removeLocal };
}
