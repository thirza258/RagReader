import React, { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonOutline, buttonPrimary, buttonQuiet, inputBase, inputSmall } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import type { ChatMessage } from "../../chat/types";
import { addDatasetItems, createDataset, getDraftFromMessage } from "../api/evaluation";
import { useDatasets } from "../hooks/useDatasets";
import { ITEM_LIMITS, validateItemInput } from "../lib/datasetCsv";
import { evidenceToExpected, tagsFromText } from "../lib/itemForm";
import type { Dataset, FromMessageDraft } from "../types";
import ApiErrorNotice from "./ApiErrorNotice";

const NEW_DATASET = "new";

interface AddToDatasetDialogProps {
  workspaceId: number;
  message: ChatMessage;
  onClose: () => void;
  /** After the item was saved: the dataset and its new version number. */
  onSaved: (dataset: Pick<Dataset, "id" | "name">, version: number) => void;
}

interface DraftState {
  datasetId: number;
  draft: FromMessageDraft | null;
  error: ApiRequestError | null;
}

function DraftForm({
  dataset,
  draft,
  onSaved,
}: {
  dataset: Dataset;
  draft: FromMessageDraft;
  onSaved: (version: number) => void;
}) {
  const [question, setQuestion] = useState(draft.draft.question ?? "");
  // Never prefilled with the model's answer: that would make correctness circular.
  const [expectedAnswer, setExpectedAnswer] = useState("");
  const [tags, setTags] = useState("");
  const [picked, setPicked] = useState<Set<number>>(() => new Set(draft.sources.map((source, index) => (source.suggested ? index : -1)).filter((index) => index >= 0)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiRequestError | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const history = draft.draft.history ?? [];

  const toggle = (index: number) =>
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    const sources = draft.sources.filter((_source, index) => picked.has(index)).map((source) => evidenceToExpected(source, draft.draft.expected_sources ?? []));
    const checked = validateItemInput({
      question,
      expected_answer: expectedAnswer,
      expected_sources: sources,
      history,
      tags: tagsFromText(tags),
      metadata: { ...(draft.draft.metadata ?? {}) },
    });
    setProblems(checked.errors.map((problem) => problem.message));
    if (!checked.item) return;
    setBusy(true);
    setError(null);
    try {
      // Appending does not depend on the latest items, so no base version is sent.
      const result = await addDatasetItems(dataset.id, [checked.item]);
      onSaved(result.version.number);
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="space-y-3" onSubmit={(event) => void save(event)} noValidate>
      <label htmlFor="add-to-dataset-question" className="flex flex-col gap-0.5 font-medium">
        Question
        <textarea
          id="add-to-dataset-question"
          rows={2}
          maxLength={ITEM_LIMITS.question}
          className={`${inputBase} text-sm font-normal`}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
        />
      </label>
      {history.length > 0 && (
        <p className="text-[11px] text-muted-foreground">
          A follow-up: the {history.length} earlier {history.length === 1 ? "turn" : "turns"} of the conversation are kept with it, so it is asked (and rewritten) the way chat did.
        </p>
      )}
      <label htmlFor="add-to-dataset-answer" className="flex flex-col gap-0.5 font-medium">
        Expected answer <span className="font-normal text-muted-foreground">(optional — type what a correct answer says; the model's answer is not copied)</span>
        <textarea
          id="add-to-dataset-answer"
          rows={2}
          maxLength={ITEM_LIMITS.expectedAnswer}
          className={`${inputBase} text-sm font-normal`}
          value={expectedAnswer}
          onChange={(event) => setExpectedAnswer(event.target.value)}
        />
      </label>
      <fieldset className="space-y-1">
        <legend className="font-medium">Expected sources</legend>
        <p className="text-[11px] text-muted-foreground">The passages the answer cited are selected; keep only the ones that really answer the question.</p>
        {draft.sources.length === 0 && <p className="text-[11px] text-muted-foreground">This answer had no sources.</p>}
        <ul className="max-h-56 space-y-1 overflow-y-auto">
          {draft.sources.map((source, index) => (
            <li key={`${source.citation_id}-${index}`}>
              <label className="flex items-start gap-2 border border-border p-1.5">
                <input type="checkbox" className="mt-0.5" checked={picked.has(index)} onChange={() => toggle(index)} />
                <span className="min-w-0">
                  <span className="block font-medium">
                    [{source.citation_id}] {source.document_title}
                    {source.page_number != null ? ` · p. ${source.page_number}` : ""}
                    {source.cited ? <span className="ml-1 text-[11px] font-normal text-status-success">cited</span> : null}
                  </span>
                  <span className="line-clamp-2 block text-[11px] text-muted-foreground">{source.text}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      </fieldset>
      <label htmlFor="add-to-dataset-tags" className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
        Tags (comma separated)
        <input id="add-to-dataset-tags" className={`${inputSmall} text-xs`} value={tags} onChange={(event) => setTags(event.target.value)} />
      </label>
      {problems.length > 0 && (
        <ul className="list-disc pl-4 text-[11px] text-destructive">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}
      {error && <ApiErrorNotice title="Could not add the question" error={error} />}
      <button type="submit" className={buttonPrimary} disabled={busy || !question.trim()}>
        {busy ? "Saving…" : `Add to “${dataset.name}”`}
      </button>
    </form>
  );
}

/**
 * "Add to dataset" on a chat answer (PRD §26): the question becomes a
 * dataset item whose expected sources are the answer's cited passages, for
 * the user to confirm. The server drafts it; nothing is saved until "Add".
 */
const AddToDatasetDialog: React.FC<AddToDatasetDialogProps> = ({ workspaceId, message, onClose, onSaved }) => {
  const datasets = useDatasets(workspaceId);
  const [choice, setChoice] = useState<string>("");
  const [newName, setNewName] = useState("");
  const [created, setCreated] = useState<Dataset | null>(null);
  const [busy, setBusy] = useState(false);
  const [createError, setCreateError] = useState<ApiRequestError | null>(null);
  const [draftState, setDraftState] = useState<DraftState | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const list = created && !datasets.list.some((item) => item.id === created.id) ? [created, ...datasets.list] : datasets.list;
  const effectiveChoice = choice || (list[0] ? String(list[0].id) : datasets.everLoaded ? NEW_DATASET : "");
  const dataset = effectiveChoice && effectiveChoice !== NEW_DATASET ? (list.find((item) => String(item.id) === effectiveChoice) ?? null) : null;
  const datasetId = dataset?.id ?? null;

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (datasetId == null) return;
    const controller = new AbortController();
    getDraftFromMessage(datasetId, message.id, controller.signal).then(
      (draft) => setDraftState({ datasetId, draft, error: null }),
      (error) => {
        if (!controller.signal.aborted) setDraftState({ datasetId, draft: null, error: toApiError(error) });
      },
    );
    return () => controller.abort();
  }, [datasetId, message.id]);

  const draft = draftState?.datasetId === datasetId ? draftState : null;

  const createAndUse = async () => {
    if (!newName.trim()) return;
    setBusy(true);
    setCreateError(null);
    try {
      const next = await createDataset({ workspaceId, name: newName.trim() });
      setCreated(next);
      setChoice(String(next.id));
      datasets.store(next);
    } catch (caught) {
      setCreateError(toApiError(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-to-dataset-title"
        tabIndex={-1}
        className="max-h-[90vh] w-full max-w-xl overflow-y-auto border border-border bg-background p-4 text-xs shadow-lg outline-none"
      >
        <div className="mb-3 flex items-start justify-between gap-2">
          <div>
            <h2 id="add-to-dataset-title" className="text-base font-medium">
              Add to dataset
            </h2>
            <p className="text-muted-foreground">Turn this question and its cited evidence into an evaluation question.</p>
          </div>
          <button type="button" className={buttonQuiet} onClick={onClose} aria-label="Close">
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>

        <div className="mb-3 space-y-2">
          <label htmlFor="add-to-dataset-choice" className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
            Dataset
            <select id="add-to-dataset-choice" className={`${inputSmall} text-xs`} value={effectiveChoice} onChange={(event) => setChoice(event.target.value)}>
              {!datasets.everLoaded && list.length === 0 && <option value="">Loading datasets…</option>}
              {list.map((item) => (
                <option key={item.id} value={String(item.id)}>
                  {item.name} (v{item.version?.number ?? "?"}, {item.version?.item_count ?? 0} questions)
                </option>
              ))}
              <option value={NEW_DATASET}>New dataset…</option>
            </select>
          </label>
          {effectiveChoice === NEW_DATASET && (
            <div className="flex items-end gap-2">
              <label htmlFor="add-to-dataset-new" className="flex flex-1 flex-col gap-0.5 text-[11px] text-muted-foreground">
                Name of the new dataset
                <input id="add-to-dataset-new" className={`${inputSmall} text-xs`} value={newName} maxLength={120} onChange={(event) => setNewName(event.target.value)} />
              </label>
              <button type="button" className={buttonOutline} disabled={busy || !newName.trim()} onClick={() => void createAndUse()}>
                Create
              </button>
            </div>
          )}
          {createError && <ApiErrorNotice title="Could not create the dataset" error={createError} />}
          {datasets.error && <ErrorNotice title="Could not load the datasets" code={datasets.error.code} message={datasets.error.message} />}
        </div>

        {dataset && !draft && (
          <p role="status" className="text-muted-foreground">
            Preparing the question…
          </p>
        )}
        {dataset && draft?.error && <ApiErrorNotice title="This answer cannot be added" error={draft.error} />}
        {dataset && draft?.draft && (
          <DraftForm
            key={`${dataset.id}-${message.id}`}
            dataset={dataset}
            draft={draft.draft}
            onSaved={(version) => onSaved({ id: dataset.id, name: dataset.name }, version)}
          />
        )}
      </div>
    </div>
  );
};

export default AddToDatasetDialog;
