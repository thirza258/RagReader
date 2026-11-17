import React, { useMemo, useState } from "react";
import { Upload } from "lucide-react";
import { buttonOutline, buttonPrimary, eyebrow, inputSmall } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import { importIntoDataset, importNewDataset } from "../api/evaluation";
import { CSV_COLUMNS, detectFormat, parseDatasetFile } from "../lib/datasetCsv";
import type { ImportMode, ImportResult } from "../types";
import ApiErrorNotice from "./ApiErrorNotice";

const PREVIEW_ROWS = 8;
const MAX_IMPORT_CHARS = 5 * 1024 * 1024;

type ImportTarget = { kind: "new"; workspaceId: number } | { kind: "existing"; datasetId: number; baseVersion: number | null };

interface ImportPanelProps {
  idPrefix: string;
  target: ImportTarget;
  onDone: (result: ImportResult) => void;
  onCancel: () => void;
}

/**
 * Import items from a JSON or CSV file, or pasted text: the file is parsed
 * here first (the same rules as the server) so every problem shows with its
 * row before anything is sent; the server then parses the same text again.
 */
const ImportPanel: React.FC<ImportPanelProps> = ({ idPrefix, target, onDone, onCancel }) => {
  const [content, setContent] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [mode, setMode] = useState<ImportMode>("append");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiRequestError | null>(null);
  const [readError, setReadError] = useState<string | null>(null);

  const parsed = useMemo(() => (content.trim() ? parseDatasetFile(content, fileName) : null), [content, fileName]);
  const format = detectFormat(content, fileName);
  const tooLarge = content.length > MAX_IMPORT_CHARS;
  const canImport = !!parsed && parsed.errors.length === 0 && parsed.items.length > 0 && !tooLarge && !busy;

  const readFile = async (file: File | undefined) => {
    setReadError(null);
    if (!file) return;
    if (file.size > MAX_IMPORT_CHARS) {
      setReadError("The file is larger than 5 MB.");
      return;
    }
    try {
      setContent(await file.text());
      setFileName(file.name);
      if (!name && target.kind === "new") setName(file.name.replace(/\.(csv|json)$/i, ""));
    } catch {
      setReadError("The file could not be read.");
    }
  };

  const submit = async () => {
    if (!canImport) return;
    setBusy(true);
    setError(null);
    try {
      const result =
        target.kind === "new"
          ? await importNewDataset({ workspaceId: target.workspaceId, name: name.trim() || undefined, format, content })
          : await importIntoDataset(target.datasetId, { format, content, mode, baseVersion: target.baseVersion });
      onDone(result);
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="space-y-2 border border-border p-3 text-xs" aria-labelledby={`${idPrefix}-import-title`}>
      <h4 id={`${idPrefix}-import-title`} className="text-sm font-medium">
        {target.kind === "new" ? "Import a dataset" : "Import items"}
      </h4>
      <p className="text-muted-foreground">
        JSON (an export, or a list of items) or CSV with a header row: <span className="font-mono">{CSV_COLUMNS.join(", ")}</span> — only{" "}
        <span className="font-mono">question</span> is required. Sources in CSV may be compact: <span className="font-mono">12#p4; 14#c345,10234-10746</span>.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label htmlFor={`${idPrefix}-import-file`} className={`${buttonOutline} cursor-pointer`}>
          <Upload aria-hidden="true" className="h-3.5 w-3.5" />
          Choose a file
          <input
            id={`${idPrefix}-import-file`}
            type="file"
            accept=".csv,.json,text/csv,application/json"
            className="sr-only"
            onChange={(event) => void readFile(event.target.files?.[0])}
          />
        </label>
        {fileName && <span className="font-mono text-[11px] text-muted-foreground">{fileName}</span>}
        {target.kind === "new" && (
          <label htmlFor={`${idPrefix}-import-name`} className="flex min-w-[12rem] flex-1 flex-col gap-0.5 text-[11px] text-muted-foreground">
            Dataset name
            <input id={`${idPrefix}-import-name`} className={`${inputSmall} text-xs`} value={name} maxLength={120} onChange={(event) => setName(event.target.value)} />
          </label>
        )}
        {target.kind === "existing" && (
          <fieldset className="flex items-center gap-3">
            <legend className="sr-only">Import mode</legend>
            {(["append", "replace"] as const).map((value) => (
              <label key={value} className="flex items-center gap-1">
                <input type="radio" name={`${idPrefix}-import-mode`} value={value} checked={mode === value} onChange={() => setMode(value)} />
                {value === "append" ? "Add to the items" : "Replace all items"}
              </label>
            ))}
          </fieldset>
        )}
      </div>
      <label htmlFor={`${idPrefix}-import-text`} className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
        …or paste the file's contents
        <textarea
          id={`${idPrefix}-import-text`}
          rows={5}
          className={`${inputSmall} w-full font-mono text-xs`}
          value={content}
          onChange={(event) => {
            setContent(event.target.value);
            setFileName(null);
          }}
        />
      </label>
      {readError && <p className="text-destructive">{readError}</p>}
      {tooLarge && <p className="text-destructive">The content is larger than 5 MB.</p>}

      {parsed && (
        <div className="space-y-1.5" aria-live="polite">
          <p>
            <span className={eyebrow}>{parsed.format.toUpperCase()}</span> {parsed.rows} {parsed.rows === 1 ? "row" : "rows"} · {parsed.items.length} valid
            {parsed.errors.length > 0 && <span className="text-destructive"> · {parsed.errors.length} {parsed.errors.length === 1 ? "problem" : "problems"}</span>}
            {parsed.ignoredColumns.length > 0 && <span className="text-muted-foreground"> · ignored columns: {parsed.ignoredColumns.join(", ")}</span>}
          </p>
          {parsed.errors.length > 0 && (
            <ul className="max-h-40 list-disc overflow-y-auto pl-4 text-[11px] text-destructive">
              {parsed.errors.slice(0, 50).map((problem, index) => (
                <li key={index}>
                  {problem.row > 0 ? `Row ${problem.row}` : "File"} · <span className="font-mono">{problem.field}</span>: {problem.message}
                </li>
              ))}
            </ul>
          )}
          {parsed.items.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-[11px]">
                <caption className="sr-only">The first rows that will be imported</caption>
                <thead className="text-muted-foreground">
                  <tr className="border-b border-border">
                    <th scope="col" className="py-1 pr-2 font-normal">Id</th>
                    <th scope="col" className="py-1 pr-2 font-normal">Question</th>
                    <th scope="col" className="py-1 pr-2 font-normal">Sources</th>
                    <th scope="col" className="py-1 pr-2 font-normal">Expected answer</th>
                  </tr>
                </thead>
                <tbody>
                  {parsed.items.slice(0, PREVIEW_ROWS).map((item, index) => (
                    <tr key={index} className="border-b border-border/60 align-top">
                      <td className="py-1 pr-2 font-mono">{item.item_id ?? "auto"}</td>
                      <td className="max-w-[16rem] py-1 pr-2">{item.question}</td>
                      <td className="py-1 pr-2 tabular">{item.expected_sources?.length ?? 0}</td>
                      <td className="max-w-[12rem] truncate py-1 pr-2">{item.expected_answer || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {parsed.items.length > PREVIEW_ROWS && <p className="mt-1 text-[11px] text-muted-foreground">…and {parsed.items.length - PREVIEW_ROWS} more.</p>}
            </div>
          )}
        </div>
      )}

      {error && <ApiErrorNotice title="The import was refused" error={error} />}
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonPrimary} disabled={!canImport} onClick={() => void submit()}>
          {busy ? "Importing…" : target.kind === "existing" && mode === "replace" ? "Replace items" : "Import"}
        </button>
        <button type="button" className={buttonOutline} onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
      {parsed && parsed.errors.length > 0 && <p className="text-[11px] text-muted-foreground">Fix the problems above to import: the server refuses a file with any invalid row.</p>}
    </section>
  );
};

export default ImportPanel;
