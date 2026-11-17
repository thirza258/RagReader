import React, { useState } from "react";
import { buttonOutline, buttonPrimary, inputBase, inputSmall } from "../../../components/ui/classes";
import type { ApiRequestError } from "../../../services/api/errors";
import type { WorkspaceDocument } from "../../documents/types";
import { ITEM_LIMITS, validateItemInput, type FieldError } from "../lib/datasetCsv";
import { sourcesFromDrafts, tagsFromText, tagsText, toSourceDraft, type SourceDraft } from "../lib/itemForm";
import type { DatasetItemInput } from "../types";
import ApiErrorNotice from "./ApiErrorNotice";
import SourceEditor from "./SourceEditor";

interface ItemFormProps {
  idPrefix: string;
  documents: readonly WorkspaceDocument[];
  /** The item being edited (its id cannot change), or a draft to start from. */
  initial?: DatasetItemInput | null;
  editing?: boolean;
  submitLabel: string;
  busy?: boolean;
  serverError?: ApiRequestError | null;
  onSubmit: (item: DatasetItemInput) => void;
  onCancel: () => void;
}

function jsonText(value: unknown, empty: string): string {
  if (value == null) return empty;
  if (Array.isArray(value) && value.length === 0) return empty;
  if (typeof value === "object" && !Array.isArray(value) && Object.keys(value as object).length === 0) return empty;
  return JSON.stringify(value, null, 2);
}

/**
 * One dataset item: the question, an optional expected answer (what the
 * judge compares the answer with), expected sources, tags and, under
 * "More", the conversation before a follow-up question and free metadata.
 * Checked with the import rules before it is sent.
 */
const ItemForm: React.FC<ItemFormProps> = ({ idPrefix, documents, initial, editing = false, submitLabel, busy = false, serverError, onSubmit, onCancel }) => {
  const [itemId, setItemId] = useState(initial?.item_id ?? "");
  const [question, setQuestion] = useState(initial?.question ?? "");
  const [expectedAnswer, setExpectedAnswer] = useState(initial?.expected_answer ?? "");
  const [tags, setTags] = useState(tagsText(initial?.tags));
  const [sources, setSources] = useState<SourceDraft[]>(() => (initial?.expected_sources ?? []).map(toSourceDraft));
  const [history, setHistory] = useState(() => jsonText(initial?.history, ""));
  const [metadata, setMetadata] = useState(() => jsonText(initial?.metadata, ""));
  const [errors, setErrors] = useState<FieldError[]>([]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const problems: FieldError[] = [];
    const built = sourcesFromDrafts(sources);
    if (built.errors.length) problems.push({ field: "expected_sources", message: built.errors.join(" ") });
    let parsedHistory: unknown = [];
    let parsedMetadata: unknown = {};
    try {
      parsedHistory = history.trim() ? JSON.parse(history) : [];
    } catch {
      problems.push({ field: "history", message: "History must be a JSON list of turns." });
    }
    try {
      parsedMetadata = metadata.trim() ? JSON.parse(metadata) : {};
    } catch {
      problems.push({ field: "metadata", message: "Metadata must be a JSON object." });
    }
    const checked = validateItemInput({
      ...(itemId.trim() && !editing ? { item_id: itemId.trim() } : {}),
      question,
      expected_answer: expectedAnswer,
      expected_sources: built.sources,
      tags: tagsFromText(tags),
      history: parsedHistory,
      metadata: parsedMetadata,
    });
    problems.push(...checked.errors.filter((error) => !problems.some((known) => known.field === error.field)));
    setErrors(problems);
    if (problems.length === 0 && checked.item) onSubmit(checked.item);
  };

  const errorFor = (field: string) => errors.find((error) => error.field === field)?.message;
  const fieldId = (name: string) => `${idPrefix}-${name}`;

  return (
    <form className="space-y-3 text-xs" onSubmit={submit} noValidate>
      <div className="grid gap-2 sm:grid-cols-[10rem_1fr]">
        <label htmlFor={fieldId("item-id")} className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
          Item id
          <input
            id={fieldId("item-id")}
            className={`${inputSmall} font-mono text-xs`}
            value={itemId}
            disabled={editing}
            placeholder="automatic (q1, q2…)"
            onChange={(event) => setItemId(event.target.value)}
            aria-invalid={!!errorFor("item_id")}
          />
        </label>
        <label htmlFor={fieldId("tags")} className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
          Tags (comma or semicolon separated)
          <input id={fieldId("tags")} className={`${inputSmall} text-xs`} value={tags} onChange={(event) => setTags(event.target.value)} aria-invalid={!!errorFor("tags")} />
        </label>
      </div>
      {errorFor("item_id") && <p className="text-[11px] text-destructive">{errorFor("item_id")}</p>}
      {errorFor("tags") && <p className="text-[11px] text-destructive">{errorFor("tags")}</p>}

      <label htmlFor={fieldId("question")} className="flex flex-col gap-0.5 font-medium">
        Question
        <textarea
          id={fieldId("question")}
          rows={2}
          maxLength={ITEM_LIMITS.question}
          className={`${inputBase} text-sm font-normal`}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          aria-invalid={!!errorFor("question")}
          required
        />
      </label>
      {errorFor("question") && <p className="text-[11px] text-destructive">{errorFor("question")}</p>}

      <label htmlFor={fieldId("answer")} className="flex flex-col gap-0.5 font-medium">
        Expected answer <span className="font-normal text-muted-foreground">(optional; the judge scores answer correctness against it)</span>
        <textarea
          id={fieldId("answer")}
          rows={2}
          maxLength={ITEM_LIMITS.expectedAnswer}
          className={`${inputBase} text-sm font-normal`}
          value={expectedAnswer}
          onChange={(event) => setExpectedAnswer(event.target.value)}
          aria-invalid={!!errorFor("expected_answer")}
        />
      </label>
      {errorFor("expected_answer") && <p className="text-[11px] text-destructive">{errorFor("expected_answer")}</p>}

      <SourceEditor idPrefix={idPrefix} sources={sources} documents={documents} onChange={setSources} disabled={busy} />
      {errorFor("expected_sources") && <p className="text-[11px] text-destructive">{errorFor("expected_sources")}</p>}

      <details className="border border-border p-2">
        <summary className="cursor-pointer text-xs font-medium">More: conversation history and metadata</summary>
        <label htmlFor={fieldId("history")} className="mt-2 flex flex-col gap-0.5 text-[11px] text-muted-foreground">
          Conversation before the question (JSON list of {"{"}"role": "user" | "assistant", "content"{"}"}, at most {ITEM_LIMITS.history} turns)
          <textarea id={fieldId("history")} rows={3} className={`${inputSmall} font-mono text-xs`} value={history} onChange={(event) => setHistory(event.target.value)} placeholder="[]" />
        </label>
        {errorFor("history") && <p className="text-[11px] text-destructive">{errorFor("history")}</p>}
        <label htmlFor={fieldId("metadata")} className="mt-2 flex flex-col gap-0.5 text-[11px] text-muted-foreground">
          Metadata (JSON object, at most 8 KB)
          <textarea id={fieldId("metadata")} rows={2} className={`${inputSmall} font-mono text-xs`} value={metadata} onChange={(event) => setMetadata(event.target.value)} placeholder="{}" />
        </label>
        {errorFor("metadata") && <p className="text-[11px] text-destructive">{errorFor("metadata")}</p>}
      </details>

      {serverError && <ApiErrorNotice title="Could not save the item" error={serverError} />}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={buttonPrimary} disabled={busy}>
          {submitLabel}
        </button>
        <button type="button" className={buttonOutline} onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
};

export default ItemForm;
