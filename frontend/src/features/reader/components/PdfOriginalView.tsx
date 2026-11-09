import React, { useEffect, useState } from "react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonOutline } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import { fetchDocumentFile } from "../../documents/api/documents";

interface PdfOriginalViewProps {
  documentId: number;
  title: string;
  page: number;
}

interface FileState {
  key: string;
  url?: string;
  error?: ApiRequestError;
}

/**
 * The original PDF in the browser's own viewer. The file endpoint needs the
 * bearer token, which an <iframe src> cannot send, so the file is fetched as
 * a blob and shown from an object URL (revoked when the document changes or
 * the view closes). The iframe is keyed by page because changing only the
 * `#page=` fragment does not make every viewer jump.
 */
const PdfOriginalView: React.FC<PdfOriginalViewProps> = ({ documentId, title, page }) => {
  const [file, setFile] = useState<FileState | null>(null);
  const [attempt, setAttempt] = useState(0);
  const key = `${documentId}:${attempt}`;

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    fetchDocumentFile(documentId, controller.signal).then(
      (blob) => {
        if (controller.signal.aborted) return;
        // Typed explicitly so the browser renders it instead of downloading it.
        objectUrl = URL.createObjectURL(new Blob([blob], { type: "application/pdf" }));
        setFile({ key: `${documentId}:${attempt}`, url: objectUrl });
      },
      (error) => {
        if (!controller.signal.aborted) setFile({ key: `${documentId}:${attempt}`, error: toApiError(error) });
      },
    );
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [documentId, attempt]);

  const current = file?.key === key ? file : null;

  if (!current) {
    return (
      <p role="status" className="p-4 text-sm text-muted-foreground">
        Loading the original PDF…
      </p>
    );
  }
  if (current.error || !current.url) {
    return (
      <div className="p-4">
        <ErrorNotice
          title="The original file could not be opened"
          code={current.error?.code}
          message={current.error?.message ?? "The file is not available."}
          actions={
            <button type="button" className={buttonOutline} onClick={() => setAttempt((value) => value + 1)}>
              Try again
            </button>
          }
        />
      </div>
    );
  }
  const safePage = Number.isInteger(page) && page > 0 ? page : 1;
  return <iframe key={`${current.url}#${safePage}`} src={`${current.url}#page=${safePage}`} title={`${title} — original PDF, page ${safePage}`} className="h-full min-h-[60vh] w-full flex-1 border-0 bg-muted" />;
};

export default PdfOriginalView;
