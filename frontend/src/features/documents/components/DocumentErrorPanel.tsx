import React from "react";
import { RotateCcw } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonOutline } from "../../../components/ui/classes";
import { stageName } from "../lib/ingestionStages";
import type { WorkspaceDocument } from "../types";

interface DocumentErrorPanelProps {
  document: WorkspaceDocument;
  busy: boolean;
  onRetry: () => void;
}

/**
 * A failed ingestion in the PRD §38 shape: which stage, why, and what to do.
 * Retry is offered when the server says the failure is retryable; otherwise
 * re-indexing is still possible, but the reason usually needs fixing first.
 */
const DocumentErrorPanel: React.FC<DocumentErrorPanelProps> = ({ document, busy, onRetry }) => {
  const error = document.error;
  const stage = stageName(error?.stage);
  const retryable = error?.retryable !== false;
  return (
    <ErrorNotice
      className="mt-2"
      title="Ingestion failed"
      code={error?.code}
      message={error?.message || "This document could not be processed."}
      actions={
        <button type="button" className={buttonOutline} onClick={onRetry} disabled={busy} aria-label={`Retry ingestion of ${document.title}`}>
          <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" />
          {busy ? "Starting…" : retryable ? "Retry ingestion" : "Re-index anyway"}
        </button>
      }
    >
      <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 text-xs">
        <dt className="text-muted-foreground">Stage</dt>
        <dd>{stage ?? "Before processing started"}</dd>
        <dt className="text-muted-foreground">Retry</dt>
        <dd>{retryable ? "Likely to succeed — the cause looks temporary." : "Unlikely to help until the cause is fixed."}</dd>
      </dl>
    </ErrorNotice>
  );
};

export default DocumentErrorPanel;
