import React, { useState } from "react";
import { FileText, Globe, Type } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonDanger, buttonOutline, buttonPrimary, buttonQuiet, buttonQuietDanger, focusRing, inputSmall } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import { formatBytes } from "../lib/uploadValidation";
import { documentMetaLine, formatDateTime, sourceLabel } from "../lib/format";
import { isTerminalStatus } from "../lib/ingestionStages";
import type { WorkspaceDocument } from "../types";
import IngestionChecklist from "./IngestionChecklist";
import DocumentErrorPanel from "./DocumentErrorPanel";

export interface DocumentRowProps {
  document: WorkspaceDocument;
  /** Open in the reader right now. */
  active: boolean;
  /** Part of the active conversation's scope. */
  included: boolean;
  /** Why the "Use in chat" box cannot change, if it cannot. */
  includeLockedReason: string | null;
  onOpen: () => void;
  onToggleInclude: (include: boolean) => void;
  onRename: (title: string) => Promise<void>;
  onDelete: () => Promise<void>;
  onReindex: () => Promise<void>;
}

type Mode = "view" | "rename" | "confirm-delete";

function SourceIcon({ sourceType }: { sourceType: string }) {
  const className = "mt-0.5 h-4 w-4 shrink-0 text-muted-foreground";
  if (sourceType === "url") return <Globe aria-hidden="true" className={className} />;
  if (sourceType === "text") return <Type aria-hidden="true" className={className} />;
  return <FileText aria-hidden="true" className={className} />;
}

const DocumentRow: React.FC<DocumentRowProps> = ({
  document,
  active,
  included,
  includeLockedReason,
  onOpen,
  onToggleInclude,
  onRename,
  onDelete,
  onReindex,
}) => {
  const [mode, setMode] = useState<Mode>("view");
  const [draft, setDraft] = useState(document.title);
  const [busy, setBusy] = useState<"rename" | "delete" | "reindex" | null>(null);
  const [error, setError] = useState<{ action: string; error: ApiRequestError } | null>(null);

  const terminal = isTerminalStatus(document.status);
  const ready = document.status === "READY";
  const checkboxId = `use-in-chat-${document.id}`;

  const run = async (action: "rename" | "delete" | "reindex", work: () => Promise<void>, label: string) => {
    setBusy(action);
    setError(null);
    try {
      await work();
      if (action !== "delete") setMode("view");
    } catch (caught) {
      setError({ action: label, error: toApiError(caught) });
    } finally {
      setBusy(null);
    }
  };

  const submitRename = (event: React.FormEvent) => {
    event.preventDefault();
    const title = draft.trim();
    if (!title || title === document.title) {
      setMode("view");
      return;
    }
    void run("rename", () => onRename(title), "Rename failed");
  };

  return (
    <li className={`border-b border-border py-3 pl-3 pr-2 ${active ? "border-l-2 border-l-primary bg-muted/60 pl-[10px]" : ""}`}>
      <div className="flex items-start gap-2">
        <SourceIcon sourceType={document.source_type} />
        <div className="min-w-0 flex-1">
          {mode === "rename" ? (
            <form onSubmit={submitRename} className="flex flex-wrap items-center gap-1.5">
              <label htmlFor={`rename-document-${document.id}`} className="sr-only">
                New title for {document.title}
              </label>
              <input
                id={`rename-document-${document.id}`}
                className={`${inputSmall} min-w-0 flex-1`}
                value={draft}
                maxLength={255}
                autoFocus
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    event.preventDefault();
                    setMode("view");
                  }
                }}
              />
              <button type="submit" className={`${buttonPrimary} px-2 py-1 text-xs`} disabled={busy === "rename"}>
                {busy === "rename" ? "Saving…" : "Save"}
              </button>
              <button type="button" className={`${buttonOutline} px-2 py-1 text-xs`} onClick={() => setMode("view")}>
                Cancel
              </button>
            </form>
          ) : (
            <button
              type="button"
              onClick={onOpen}
              aria-current={active ? "true" : undefined}
              title={document.title}
              className={`block w-full truncate text-left text-sm font-medium text-foreground hover:underline ${focusRing}`}
            >
              {document.title || "Untitled document"}
            </button>
          )}
          <p className="mt-0.5 text-xs text-muted-foreground">{documentMetaLine(document)}</p>

          {!terminal && <IngestionChecklist document={document} />}
          {document.status === "FAILED" && (
            <DocumentErrorPanel document={document} busy={busy === "reindex"} onRetry={() => void run("reindex", onReindex, "Retry failed")} />
          )}

          <div className="mt-1.5 flex flex-wrap items-center gap-x-1 gap-y-1">
            <span className="mr-1 inline-flex items-center gap-1.5 text-xs" title={includeLockedReason ?? undefined}>
              <input
                id={checkboxId}
                type="checkbox"
                className="h-3.5 w-3.5 accent-primary"
                checked={included}
                disabled={!!includeLockedReason}
                onChange={(event) => onToggleInclude(event.target.checked)}
              />
              <label htmlFor={checkboxId} className={includeLockedReason ? "text-muted-foreground" : ""}>
                Use in chat<span className="sr-only">: {document.title}</span>
              </label>
            </span>
            <button type="button" className={buttonQuiet} onClick={onOpen}>
              Open<span className="sr-only"> {document.title}</span>
            </button>
            <button
              type="button"
              className={buttonQuiet}
              onClick={() => {
                setDraft(document.title);
                setError(null);
                setMode("rename");
              }}
            >
              Rename<span className="sr-only"> {document.title}</span>
            </button>
            {ready && (
              <button type="button" className={buttonQuiet} disabled={busy === "reindex"} onClick={() => void run("reindex", onReindex, "Re-index failed")}>
                {busy === "reindex" ? "Starting…" : "Re-index"}
                <span className="sr-only"> {document.title}</span>
              </button>
            )}
            <button
              type="button"
              className={buttonQuietDanger}
              onClick={() => {
                setError(null);
                setMode("confirm-delete");
              }}
            >
              Delete<span className="sr-only"> {document.title}</span>
            </button>
          </div>

          {mode === "confirm-delete" && (
            <div role="group" aria-label={`Confirm deleting ${document.title}`} className="mt-2 border border-destructive/30 bg-destructive/5 p-2.5 text-xs">
              <p>
                Delete <span className="font-medium">“{document.title}”</span>? Its stored file and index are removed, and citations to it can no
                longer be opened.
              </p>
              <div className="mt-2 flex gap-2">
                <button type="button" className={`${buttonDanger} px-2 py-1 text-xs`} disabled={busy === "delete"} onClick={() => void run("delete", onDelete, "Delete failed")}>
                  {busy === "delete" ? "Deleting…" : "Delete document"}
                </button>
                <button type="button" autoFocus className={`${buttonOutline} px-2 py-1 text-xs`} onClick={() => setMode("view")}>
                  Cancel
                </button>
              </div>
            </div>
          )}

          {error && (
            <ErrorNotice
              className="mt-2 text-xs"
              title={error.action}
              code={error.error.code}
              message={error.error.message}
              actions={
                <button type="button" className={buttonQuiet} onClick={() => setError(null)}>
                  Dismiss
                </button>
              }
            />
          )}

          <details className="mt-1 text-xs">
            <summary className={`cursor-pointer select-none text-muted-foreground hover:text-foreground ${focusRing}`}>Details</summary>
            <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-muted-foreground">
              <dt>Type</dt>
              <dd className="text-foreground/85">{sourceLabel(document.source_type)}</dd>
              {document.source && (
                <>
                  <dt>Source</dt>
                  <dd className="break-all text-foreground/85">{document.source}</dd>
                </>
              )}
              {document.file_size != null && (
                <>
                  <dt>Size</dt>
                  <dd className="text-foreground/85">{formatBytes(document.file_size)}</dd>
                </>
              )}
              {document.char_count != null && (
                <>
                  <dt>Characters</dt>
                  <dd className="text-foreground/85 tabular">{document.char_count.toLocaleString("en-US")}</dd>
                </>
              )}
              <dt>Added</dt>
              <dd className="text-foreground/85">{formatDateTime(document.created_at)}</dd>
              {document.ingested_at && (
                <>
                  <dt>Indexed</dt>
                  <dd className="text-foreground/85">{formatDateTime(document.ingested_at)}</dd>
                </>
              )}
              {document.index && (
                <>
                  <dt>Index</dt>
                  <dd className="break-all text-foreground/85">
                    #{document.index.id} · {document.index.method} · {document.index.embedding_model}
                  </dd>
                </>
              )}
              <dt>ID</dt>
              <dd className="font-mono text-foreground/85">{document.id}</dd>
            </dl>
          </details>
        </div>
      </div>
    </li>
  );
};

export default DocumentRow;
