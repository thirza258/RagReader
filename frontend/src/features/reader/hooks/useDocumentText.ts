import { useEffect, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { getDocumentText } from "../../documents/api/documents";
import type { DocumentText } from "../../documents/types";

interface TextResult {
  documentId: number;
  text?: DocumentText;
  error?: ApiRequestError;
}

/**
 * The extracted text of one document. The result is keyed by document id, so
 * switching documents shows "loading" at once instead of the previous text.
 */
export function useDocumentText(documentId: number | null, enabled: boolean) {
  const [result, setResult] = useState<TextResult | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (documentId == null || !enabled) return;
    const controller = new AbortController();
    getDocumentText(documentId, controller.signal).then(
      (text) => setResult({ documentId, text }),
      (error) => {
        if (!controller.signal.aborted) setResult({ documentId, error: toApiError(error) });
      },
    );
    return () => controller.abort();
  }, [documentId, enabled, attempt]);

  const current = result && result.documentId === documentId ? result : null;
  return {
    text: current?.text ?? null,
    error: current?.error ?? null,
    loading: documentId != null && enabled && !current,
    retry: () => {
      setResult(null);
      setAttempt((value) => value + 1);
    },
  };
}
