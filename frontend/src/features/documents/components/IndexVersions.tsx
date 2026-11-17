import React, { useEffect, useState } from "react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonQuiet, focusRing } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import { listIndexVersions } from "../../pipelines/api/pipelines";
import type { IndexVersion } from "../../pipelines/types";
import { indexBuildText, indexVersionLabel } from "../lib/indexVersions";
import { formatDateTime } from "../lib/format";

/** Loaded only while open: the document's index versions, newest first. */
function IndexList({ documentId, currentIndexId }: { documentId: number; currentIndexId: number | null }) {
  const [state, setState] = useState<{ key: string; indexes: IndexVersion[]; error: ApiRequestError | null } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const key = `${documentId}:${currentIndexId ?? ""}:${attempt}`;

  useEffect(() => {
    const controller = new AbortController();
    listIndexVersions(documentId, controller.signal).then(
      (indexes) => setState({ key, indexes, error: null }),
      (error) => {
        if (!controller.signal.aborted) setState({ key, indexes: [], error: toApiError(error) });
      },
    );
    return () => controller.abort();
  }, [documentId, key]);

  if (!state || state.key !== key) {
    return (
      <p role="status" className="mt-1 text-muted-foreground">
        Loading index versions…
      </p>
    );
  }
  if (state.error) {
    return (
      <ErrorNotice
        className="mt-1"
        title="Could not load the index versions"
        code={state.error.code}
        message={state.error.message}
        actions={
          <button type="button" className={buttonQuiet} onClick={() => setAttempt((value) => value + 1)}>
            Try again
          </button>
        }
      />
    );
  }
  if (state.indexes.length === 0) return <p className="mt-1 text-muted-foreground">No index has been built yet.</p>;
  return (
    <ol className="mt-1 space-y-1">
      {state.indexes.map((index) => (
        <li key={index.id} className={`border-l-2 pl-2 ${index.is_current ? "border-primary" : "border-border text-muted-foreground"}`}>
          <span className="font-mono">{indexVersionLabel(index)}</span>
          <span className="block">{indexBuildText(index)}</span>
          <span className="block text-[11px] text-muted-foreground">Built {formatDateTime(index.created_at)}</span>
        </li>
      ))}
    </ol>
  );
}

/**
 * A document's index versions (PRD §19): every ingestion or re-index builds
 * one, and chat searches the current one. Collapsed by default.
 */
const IndexVersions: React.FC<{ documentId: number; currentIndexId: number | null }> = ({ documentId, currentIndexId }) => {
  const [open, setOpen] = useState(false);
  return (
    <details className="mt-1 text-xs" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className={`cursor-pointer select-none text-muted-foreground hover:text-foreground ${focusRing}`}>
        Index versions{currentIndexId != null ? ` (current #${currentIndexId})` : ""}
      </summary>
      {open && <IndexList documentId={documentId} currentIndexId={currentIndexId} />}
    </details>
  );
};

export default IndexVersions;
