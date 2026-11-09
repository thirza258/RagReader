import React, { useState } from "react";
import { ChevronDown, ChevronUp, RefreshCw } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonIcon, buttonOutline, buttonQuiet, eyebrow } from "../../../components/ui/classes";
import type { ApiRequestError } from "../../../services/api/errors";
import { includedIds } from "../lib/scope";
import type { WorkspaceDocument } from "../types";
import DocumentRow from "./DocumentRow";
import UploadPanel from "./UploadPanel";

export interface ChatScope {
  /** The conversation's `document_ids`; empty means every READY document. */
  ids: number[];
  busy: boolean;
  /** The open conversation is still loading, so its scope is not known yet. */
  loading: boolean;
  error: ApiRequestError | null;
}

interface DocumentLibraryProps {
  workspaceId: number;
  documents: WorkspaceDocument[];
  loaded: boolean;
  error: ApiRequestError | null;
  /** Spoken when a document becomes ready or fails. */
  announcement: string;
  activeDocumentId: number | null;
  scope: ChatScope;
  /** Whether the scope belongs to an open conversation or to the next new one. */
  scopeTarget: "conversation" | "new";
  onOpen: (document: WorkspaceDocument) => void;
  onScopeChange: (ids: number[]) => void;
  onRefresh: () => void;
  onCreated: (document: WorkspaceDocument, warning: ApiRequestError | null) => void;
  onRename: (document: WorkspaceDocument, title: string) => Promise<void>;
  onDelete: (document: WorkspaceDocument) => Promise<void>;
  onReindex: (document: WorkspaceDocument) => Promise<void>;
  onDismissScopeError: () => void;
}

/**
 * The persistent document library (PRD §11) with ingestion progress (§9) and
 * the "Use in chat" scope of the active conversation. An empty scope means
 * "all ready documents", so it is shown as every ready document ticked;
 * unticking one turns it into an explicit list of the others.
 */
const DocumentLibrary: React.FC<DocumentLibraryProps> = ({
  workspaceId,
  documents,
  loaded,
  error,
  announcement,
  activeDocumentId,
  scope,
  scopeTarget,
  onOpen,
  onScopeChange,
  onRefresh,
  onCreated,
  onRename,
  onDelete,
  onReindex,
  onDismissScopeError,
}) => {
  const [uploadOpen, setUploadOpen] = useState<boolean | null>(null);
  const showUpload = uploadOpen ?? (loaded && documents.length === 0);

  const readyIds = documents.filter((document) => document.status === "READY").map((document) => document.id);
  const included = includedIds(scope.ids, documents);
  const includedCount = documents.filter((document) => included.has(document.id)).length;
  const allMode = scope.ids.length === 0;

  const toggle = (document: WorkspaceDocument, include: boolean) => {
    const base = allMode ? readyIds : scope.ids.filter((id) => documents.some((item) => item.id === id));
    const next = include ? [...new Set([...base, document.id])] : base.filter((id) => id !== document.id);
    if (next.length === 0) return; // an empty list would mean "everything" again
    onScopeChange(next);
  };

  const lockedReason = (document: WorkspaceDocument): string | null => {
    if (scope.loading) return "Loading the conversation…";
    if (scope.busy) return "Saving the chat scope…";
    const isIncluded = included.has(document.id);
    if (!isIncluded && document.status !== "READY") return "Available once the document is ready";
    if (isIncluded && includedCount <= 1) return "Chat needs at least one document";
    return null;
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <h2 id="documents-heading" className="font-serif text-base font-semibold">
          Documents <span className="font-sans text-xs font-normal text-muted-foreground tabular">({documents.length})</span>
        </h2>
        <div className="flex items-center gap-1">
          <button type="button" className={buttonIcon} onClick={onRefresh} aria-label="Reload document status">
            <RefreshCw aria-hidden="true" className="h-4 w-4" />
          </button>
          <button
            type="button"
            className={`${buttonOutline} px-2 py-1 text-xs`}
            aria-expanded={showUpload}
            aria-controls={`upload-panel-${workspaceId}`}
            onClick={() => setUploadOpen(!showUpload)}
          >
            Add {showUpload ? <ChevronUp aria-hidden="true" className="h-3.5 w-3.5" /> : <ChevronDown aria-hidden="true" className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto">
        {/* Kept mounted while collapsed so uploads in flight keep their rows. */}
        <section id={`upload-panel-${workspaceId}`} aria-label="Add documents" hidden={!showUpload} className="border-b border-border p-3">
          <UploadPanel
            workspaceId={workspaceId}
            onCreated={(document, warning) => {
              // The panel opened itself for an empty library; keep it open now
              // that the first document arrived, so further uploads stay visible.
              if (uploadOpen === null) setUploadOpen(true);
              onCreated(document, warning);
            }}
          />
        </section>

        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>

        <div className="border-b border-border px-3 py-2 text-xs" aria-live="polite">
          <p className={eyebrow}>{scopeTarget === "conversation" ? "This conversation uses" : "A new conversation will use"}</p>
          <p className="mt-0.5 text-foreground/85">
            {allMode
              ? `All ready documents (${readyIds.length})`
              : `${includedCount} of ${documents.length} document${documents.length === 1 ? "" : "s"}`}
            {!allMode && (
              <button type="button" className={`${buttonQuiet} ml-1`} disabled={scope.busy || scope.loading} onClick={() => onScopeChange([])}>
                Use all ready documents
              </button>
            )}
          </p>
          {scope.error && (
            <ErrorNotice
              className="mt-2"
              title="The chat scope was not saved"
              code={scope.error.code}
              message={scope.error.message}
              actions={
                <button type="button" className={buttonQuiet} onClick={onDismissScopeError}>
                  Dismiss
                </button>
              }
            />
          )}
        </div>

        {error && (
          <div className="p-3">
            <ErrorNotice
              title="Could not load the documents"
              code={error.code}
              message={error.message}
              actions={
                <button type="button" className={buttonOutline} onClick={onRefresh}>
                  Try again
                </button>
              }
            />
          </div>
        )}

        {!loaded && !error && (
          <p role="status" className="p-3 text-sm text-muted-foreground">
            Loading documents…
          </p>
        )}

        {loaded && documents.length === 0 && !error && (
          <p className="p-3 text-sm text-muted-foreground">
            No documents yet. Add a PDF, Word or text file, a web page or pasted text to start.
          </p>
        )}

        {documents.length > 0 && (
          <ul aria-labelledby="documents-heading">
            {documents.map((document) => (
              <DocumentRow
                key={document.id}
                document={document}
                active={document.id === activeDocumentId}
                included={included.has(document.id)}
                includeLockedReason={lockedReason(document)}
                onOpen={() => onOpen(document)}
                onToggleInclude={(include) => toggle(document, include)}
                onRename={(title) => onRename(document, title)}
                onDelete={() => onDelete(document)}
                onReindex={() => onReindex(document)}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};

export default DocumentLibrary;
