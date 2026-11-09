import React, { useRef, useState } from "react";
import { FileUp, X } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonOutline, buttonPrimary, buttonQuiet, focusRing, inputBase } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import { createDocument } from "../api/documents";
import {
  ACCEPT_ATTRIBUTE,
  ACCEPTED_TYPES_LABEL,
  MAX_UPLOAD_BYTES,
  formatBytes,
  validatePastedText,
  validateSourceUrl,
  validateUploadFile,
} from "../lib/uploadValidation";
import type { WorkspaceDocument } from "../types";

type SourceMode = "file" | "url" | "text";

interface UploadRow {
  key: string;
  name: string;
  /** 0–1 while uploading. */
  progress: number;
  error: { code: string; message: string } | null;
}

interface UploadPanelProps {
  workspaceId: number;
  /** A document was accepted (202), possibly with a warning (stored but not queued). */
  onCreated: (document: WorkspaceDocument, warning: ApiRequestError | null) => void;
}

const MODES: { id: SourceMode; label: string }[] = [
  { id: "file", label: "Files" },
  { id: "url", label: "Web page" },
  { id: "text", label: "Paste text" },
];

/**
 * Adds documents to the workspace: files (picker or drag-and-drop, several
 * at once), a web page URL, or pasted text. Each source is checked here the
 * way the backend will check it, then uploaded; ingestion continues in the
 * background and shows up in the library.
 */
const UploadPanel: React.FC<UploadPanelProps> = ({ workspaceId, onCreated }) => {
  const [mode, setMode] = useState<SourceMode>("file");
  const [uploads, setUploads] = useState<UploadRow[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<{ code: string; message: string } | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const counter = useRef(0);

  const updateRow = (key: string, patch: Partial<UploadRow>) =>
    setUploads((rows) => rows.map((row) => (row.key === key ? { ...row, ...patch } : row)));

  const uploadFiles = async (files: File[]) => {
    if (files.length === 0) return;
    const accepted: { file: File; key: string }[] = [];
    const rows: UploadRow[] = [];
    for (const file of files) {
      counter.current += 1;
      const key = `${counter.current}-${file.name}`;
      const problem = validateUploadFile(file);
      rows.push({ key, name: file.name, progress: 0, error: problem });
      if (!problem) accepted.push({ file, key });
    }
    setUploads((current) => [...current, ...rows]);
    for (const { file, key } of accepted) {
      try {
        const { document, warning } = await createDocument(
          { kind: "file", file },
          { workspaceId, onUploadProgress: (fraction) => updateRow(key, { progress: fraction }) },
        );
        setUploads((current) => current.filter((row) => row.key !== key));
        setAnnouncement(`Added ${document.title || file.name}. Processing has started.`);
        onCreated(document, warning);
      } catch (error) {
        const apiError = toApiError(error);
        updateRow(key, { error: { code: apiError.code, message: apiError.message } });
      }
    }
  };

  const submitSource = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);
    let input: Parameters<typeof createDocument>[0];
    if (mode === "url") {
      const checked = validateSourceUrl(url);
      if ("problem" in checked) {
        setFormError(checked.problem);
        return;
      }
      input = { kind: "url", url: checked.url, title };
    } else {
      const problem = validatePastedText(text);
      if (problem) {
        setFormError(problem);
        return;
      }
      input = { kind: "text", text, title };
    }
    setSubmitting(true);
    try {
      const { document, warning } = await createDocument(input, { workspaceId });
      setUrl("");
      setText("");
      setTitle("");
      setAnnouncement(`Added ${document.title || "the document"}. Processing has started.`);
      onCreated(document, warning);
    } catch (error) {
      const apiError = toApiError(error);
      setFormError({ code: apiError.code, message: apiError.message });
    } finally {
      setSubmitting(false);
    }
  };

  const onDrop = (event: React.DragEvent) => {
    event.preventDefault();
    setDragActive(false);
    void uploadFiles(Array.from(event.dataTransfer.files ?? []));
  };

  return (
    <div className="space-y-3">
      <div role="group" aria-label="Kind of source" className="flex border border-border">
        {MODES.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-pressed={mode === item.id}
            onClick={() => {
              setMode(item.id);
              setFormError(null);
            }}
            className={`flex-1 px-2 py-1.5 text-xs transition-colors ${focusRing} ${
              mode === item.id ? "bg-foreground text-background" : "text-muted-foreground hover:bg-accent hover:text-foreground"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {mode === "file" && (
        <div
          onDragEnter={(event) => {
            event.preventDefault();
            setDragActive(true);
          }}
          onDragOver={(event) => {
            event.preventDefault();
            event.dataTransfer.dropEffect = "copy";
          }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragActive(false);
          }}
          onDrop={onDrop}
          className={`flex flex-col items-center gap-2 border border-dashed px-3 py-5 text-center transition-colors ${
            dragActive ? "border-primary bg-primary/5" : "border-input"
          }`}
        >
          <FileUp aria-hidden="true" className="h-5 w-5 text-muted-foreground" />
          <p className="text-xs text-muted-foreground">Drop files here, or</p>
          <input
            ref={inputRef}
            id={`upload-files-${workspaceId}`}
            type="file"
            multiple
            accept={ACCEPT_ATTRIBUTE}
            className="peer sr-only"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = "";
              void uploadFiles(files);
            }}
          />
          <label
            htmlFor={`upload-files-${workspaceId}`}
            className={`${buttonOutline} cursor-pointer peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-1`}
          >
            Choose files
          </label>
          <p className="text-[11px] text-muted-foreground">
            {ACCEPTED_TYPES_LABEL} · up to {formatBytes(MAX_UPLOAD_BYTES)} each
          </p>
        </div>
      )}

      {mode !== "file" && (
        <form onSubmit={submitSource} noValidate className="space-y-2">
          {mode === "url" ? (
            <div>
              <label htmlFor={`source-url-${workspaceId}`} className="mb-1 block text-xs font-medium">
                Web page URL
              </label>
              <input
                id={`source-url-${workspaceId}`}
                type="url"
                inputMode="url"
                autoComplete="url"
                placeholder="https://example.com/article"
                className={inputBase}
                value={url}
                onChange={(event) => setUrl(event.target.value)}
              />
            </div>
          ) : (
            <div>
              <label htmlFor={`source-text-${workspaceId}`} className="mb-1 block text-xs font-medium">
                Text
              </label>
              <textarea
                id={`source-text-${workspaceId}`}
                rows={5}
                placeholder="Paste the text here…"
                className={`${inputBase} resize-y`}
                value={text}
                onChange={(event) => setText(event.target.value)}
              />
            </div>
          )}
          <div>
            <label htmlFor={`source-title-${workspaceId}`} className="mb-1 block text-xs font-medium">
              Title <span className="font-normal text-muted-foreground">(optional)</span>
            </label>
            <input
              id={`source-title-${workspaceId}`}
              type="text"
              maxLength={255}
              className={inputBase}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <button type="submit" className={`${buttonPrimary} w-full`} disabled={submitting}>
            {submitting ? "Adding…" : mode === "url" ? "Add web page" : "Add text"}
          </button>
          {formError && <ErrorNotice code={formError.code} message={formError.message} className="text-xs" />}
        </form>
      )}

      {uploads.length > 0 && (
        <ul className="space-y-2" aria-label="Uploads">
          {uploads.map((row) => (
            <li key={row.key} className="text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate" title={row.name}>
                  {row.name}
                </span>
                {row.error ? (
                  <button
                    type="button"
                    className={buttonQuiet}
                    aria-label={`Dismiss the error for ${row.name}`}
                    onClick={() => setUploads((current) => current.filter((item) => item.key !== row.key))}
                  >
                    <X aria-hidden="true" className="h-3.5 w-3.5" />
                  </button>
                ) : (
                  <span className="font-mono tabular text-muted-foreground">{Math.round(row.progress * 100)}%</span>
                )}
              </div>
              {row.error ? (
                <p role="alert" className="mt-0.5 text-destructive">
                  {row.error.message} <span className="font-mono text-[11px] text-muted-foreground">({row.error.code})</span>
                </p>
              ) : (
                <div
                  role="progressbar"
                  aria-label={`Uploading ${row.name}`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(row.progress * 100)}
                  className="mt-1 h-[3px] w-full overflow-hidden bg-muted"
                >
                  <div className="h-full bg-foreground/60 transition-[width]" style={{ width: `${Math.round(row.progress * 100)}%` }} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
    </div>
  );
};

export default UploadPanel;
