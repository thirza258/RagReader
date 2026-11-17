import React from "react";
import { Plus, Trash2 } from "lucide-react";
import { buttonQuiet, buttonQuietDanger, inputSmall } from "../../../components/ui/classes";
import type { WorkspaceDocument } from "../../documents/types";
import { emptySourceDraft, type SourceDraft } from "../lib/itemForm";
import { ITEM_LIMITS } from "../lib/datasetCsv";

interface SourceEditorProps {
  idPrefix: string;
  sources: SourceDraft[];
  documents: readonly WorkspaceDocument[];
  onChange: (sources: SourceDraft[]) => void;
  disabled?: boolean;
}

function NumberField({ id, label, value, onChange, disabled, width = "w-20" }: { id: string; label: string; value: string; onChange: (value: string) => void; disabled?: boolean; width?: string }) {
  return (
    <label htmlFor={id} className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
      {label}
      <input id={id} inputMode="numeric" className={`${inputSmall} ${width} font-mono text-xs`} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

/**
 * The expected sources of one item (PRD §26): a document of the workspace,
 * optionally narrowed to pages, a chunk id or a character range. At run
 * time the chunk is matched first, then the range, then the pages; a
 * document alone makes any of its passages relevant.
 */
const SourceEditor: React.FC<SourceEditorProps> = ({ idPrefix, sources, documents, onChange, disabled }) => {
  const update = (index: number, patch: Partial<SourceDraft>) => onChange(sources.map((source, at) => (at === index ? { ...source, ...patch } : source)));
  const remove = (index: number) => onChange(sources.filter((_source, at) => at !== index));
  const add = () => onChange([...sources, emptySourceDraft(documents.find((document) => document.status === "READY")?.id ?? documents[0]?.id ?? null)]);
  const known = new Set(documents.map((document) => String(document.id)));

  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="text-xs font-medium">Expected sources</legend>
      {sources.length === 0 && <p className="text-[11px] text-muted-foreground">None: retrieval cannot be judged for this question (it is flagged as ambiguous).</p>}
      {sources.map((source, index) => {
        const base = `${idPrefix}-source-${index}`;
        return (
          <div key={index} className="space-y-1.5 border border-border p-2">
            <div className="flex items-end gap-2">
              <label htmlFor={`${base}-document`} className="flex min-w-0 flex-1 flex-col gap-0.5 text-[11px] text-muted-foreground">
                Document
                <select
                  id={`${base}-document`}
                  className={`${inputSmall} min-w-0 text-xs`}
                  value={source.document_id}
                  onChange={(event) => update(index, { document_id: event.target.value, document_title: "" })}
                >
                  <option value="">{source.document_title ? `By title: ${source.document_title}` : "Choose a document"}</option>
                  {source.document_id && !known.has(source.document_id) && <option value={source.document_id}>Document {source.document_id} (not in this workspace)</option>}
                  {documents.map((document) => (
                    <option key={document.id} value={String(document.id)}>
                      {document.title}
                      {document.status !== "READY" ? ` (${document.status.toLowerCase()})` : ""}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" className={buttonQuietDanger} onClick={() => remove(index)} aria-label={`Remove source ${index + 1}`}>
                <Trash2 aria-hidden="true" className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              <NumberField id={`${base}-page`} label="Page" value={source.page} onChange={(value) => update(index, { page: value })} width="w-16" />
              <NumberField id={`${base}-page-end`} label="to page" value={source.page_end} onChange={(value) => update(index, { page_end: value })} width="w-16" />
              <NumberField id={`${base}-chunk`} label="Chunk id" value={source.chunk_id} onChange={(value) => update(index, { chunk_id: value })} />
              <NumberField id={`${base}-start`} label="Chars from" value={source.char_start} onChange={(value) => update(index, { char_start: value })} />
              <NumberField id={`${base}-end`} label="to" value={source.char_end} onChange={(value) => update(index, { char_end: value })} />
            </div>
            <label htmlFor={`${base}-text`} className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
              Quote (optional, for people reading the dataset)
              <textarea
                id={`${base}-text`}
                rows={2}
                maxLength={ITEM_LIMITS.sourceText}
                className={`${inputSmall} w-full text-xs`}
                value={source.text}
                onChange={(event) => update(index, { text: event.target.value })}
              />
            </label>
            {source.index_version_id != null && <p className="text-[11px] text-muted-foreground">From index version {source.index_version_id}.</p>}
          </div>
        );
      })}
      <button type="button" className={buttonQuiet} onClick={add} disabled={disabled || sources.length >= ITEM_LIMITS.sources}>
        <Plus aria-hidden="true" className="h-3.5 w-3.5" />
        Add a source
      </button>
    </fieldset>
  );
};

export default SourceEditor;
