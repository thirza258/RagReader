import React, { useState } from "react";
import { ArrowLeft, Download, FlaskConical, Pencil, Plus, Trash2, Upload } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonDanger, buttonOutline, buttonPrimary, buttonQuiet, buttonQuietDanger, eyebrow, inputSmall } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import { formatDateTime } from "../../documents/lib/format";
import type { WorkspaceDocument } from "../../documents/types";
import { addDatasetItems, deleteDataset, deleteDatasetItem, exportDataset, updateDataset, updateDatasetItem } from "../api/evaluation";
import { useDataset } from "../hooks/useDataset";
import { describeSource } from "../lib/datasetCsv";
import type { DatasetItem, DatasetItemInput, DatasetVersion } from "../types";
import ApiErrorNotice from "./ApiErrorNotice";
import ImportPanel from "./ImportPanel";
import ItemForm from "./ItemForm";

type Mode =
  | { kind: "items" }
  | { kind: "add" }
  | { kind: "edit"; itemId: string }
  | { kind: "import" }
  | { kind: "corpus" }
  | { kind: "rename" }
  | { kind: "confirm-delete" };

interface DatasetEditorProps {
  datasetId: number;
  documents: readonly WorkspaceDocument[];
  onBack: () => void;
  /** After any change, so lists elsewhere stay current. */
  onChanged: () => void;
  onDeleted: (id: number) => void;
  /** Start an experiment on this dataset version. */
  onLaunch: (datasetId: number, version: number) => void;
}

function ChecksSummary({ version }: { version: DatasetVersion }) {
  const checks = version.checks;
  if (!checks) return null;
  const lines: string[] = [];
  if (checks.items_without_sources.length) lines.push(`Without expected sources (ambiguous): ${checks.items_without_sources.join(", ")}`);
  if (checks.duplicate_questions.length) lines.push(`Duplicate questions: ${checks.duplicate_questions.map((group) => group.join(" = ")).join("; ")}`);
  if (checks.missing_documents.length) lines.push(`Sources naming a document that is gone or outside the corpus: ${checks.missing_documents.join(", ")}`);
  if (lines.length === 0) return <p className="text-[11px] text-status-success">No dataset problems found in this version.</p>;
  return (
    <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-status-warning">
      {lines.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}

function CorpusEditor({
  documents,
  selected,
  busy,
  onSave,
  onCancel,
}: {
  documents: readonly WorkspaceDocument[];
  selected: readonly number[];
  busy: boolean;
  onSave: (ids: number[]) => void;
  onCancel: () => void;
}) {
  const [ids, setIds] = useState<number[]>([...selected]);
  const toggle = (id: number) => setIds((current) => (current.includes(id) ? current.filter((value) => value !== id) : [...current, id]));
  return (
    <fieldset className="space-y-1.5 border border-border p-3" disabled={busy}>
      <legend className="px-1 text-xs font-medium">Documents searched</legend>
      <p className="text-[11px] text-muted-foreground">None selected: every READY document of the workspace when the experiment starts (the experiment records which).</p>
      <ul className="max-h-48 space-y-0.5 overflow-y-auto">
        {documents.map((document) => (
          <li key={document.id}>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={ids.includes(document.id)} onChange={() => toggle(document.id)} />
              <span className="truncate">{document.title}</span>
              {document.status !== "READY" && <span className="text-[11px] text-muted-foreground">({document.status.toLowerCase()})</span>}
            </label>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <button type="button" className={buttonPrimary} onClick={() => onSave([...ids].sort((a, b) => a - b))}>
          Save as a new version
        </button>
        <button type="button" className={buttonOutline} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </fieldset>
  );
}

function RenameForm({ name, description, busy, onSave, onCancel }: { name: string; description: string; busy: boolean; onSave: (name: string, description: string) => void; onCancel: () => void }) {
  const [nextName, setNextName] = useState(name);
  const [nextDescription, setNextDescription] = useState(description);
  return (
    <form
      className="space-y-2 border border-border p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (nextName.trim()) onSave(nextName.trim(), nextDescription.trim());
      }}
    >
      <label htmlFor="dataset-rename-name" className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
        Name
        <input id="dataset-rename-name" className={`${inputSmall} text-xs`} value={nextName} maxLength={120} required onChange={(event) => setNextName(event.target.value)} />
      </label>
      <label htmlFor="dataset-rename-description" className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
        Description
        <textarea id="dataset-rename-description" rows={2} className={`${inputSmall} text-xs`} value={nextDescription} maxLength={2000} onChange={(event) => setNextDescription(event.target.value)} />
      </label>
      <p className="text-[11px] text-muted-foreground">Renaming does not create a version.</p>
      <div className="flex gap-2">
        <button type="submit" className={buttonPrimary} disabled={busy || !nextName.trim()}>
          Save
        </button>
        <button type="button" className={buttonOutline} onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function ItemsTable({
  items,
  editable,
  busy,
  titleFor,
  onEdit,
  onDelete,
}: {
  items: readonly DatasetItem[];
  editable: boolean;
  busy: boolean;
  titleFor: (id: number) => string | null;
  onEdit: (itemId: string) => void;
  onDelete: (itemId: string) => void;
}) {
  const [confirming, setConfirming] = useState<string | null>(null);
  if (items.length === 0) return <p className="text-muted-foreground">This version has no questions yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-[11px]">
        <caption className="sr-only">Questions of this dataset version</caption>
        <thead className="text-muted-foreground">
          <tr className="border-b border-border">
            <th scope="col" className="py-1 pr-2 font-normal">Id</th>
            <th scope="col" className="py-1 pr-2 font-normal">Question</th>
            <th scope="col" className="py-1 pr-2 font-normal">Expected sources</th>
            <th scope="col" className="py-1 pr-2 font-normal">Answer</th>
            <th scope="col" className="py-1 pr-2 font-normal">Tags</th>
            {editable && (
              <th scope="col" className="py-1 font-normal">
                <span className="sr-only">Actions</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.item_id} className="border-b border-border/60 align-top">
              <td className="py-1 pr-2 font-mono">{item.item_id}</td>
              <td className="min-w-[12rem] max-w-[22rem] py-1 pr-2">
                {item.question}
                {item.history.length > 0 && <span className="block text-muted-foreground">follow-up · {item.history.length} earlier turns</span>}
              </td>
              <td className="min-w-[10rem] py-1 pr-2">
                {item.expected_sources.length === 0 ? (
                  <span className="text-status-warning">none</span>
                ) : (
                  <ul className="space-y-0.5">
                    {item.expected_sources.map((source, index) => (
                      <li key={index}>{describeSource(source, titleFor)}</li>
                    ))}
                  </ul>
                )}
              </td>
              <td className="max-w-[12rem] py-1 pr-2">{item.expected_answer ? <span className="line-clamp-2">{item.expected_answer}</span> : <span className="text-muted-foreground">—</span>}</td>
              <td className="py-1 pr-2">{item.tags.join(", ") || "—"}</td>
              {editable && (
                <td className="whitespace-nowrap py-1">
                  {confirming === item.item_id ? (
                    <span className="flex items-center gap-1">
                      <button
                        type="button"
                        className={buttonQuietDanger}
                        disabled={busy}
                        onClick={() => {
                          setConfirming(null);
                          onDelete(item.item_id);
                        }}
                      >
                        Delete {item.item_id}
                      </button>
                      <button type="button" className={buttonQuiet} onClick={() => setConfirming(null)}>
                        Keep
                      </button>
                    </span>
                  ) : (
                    <span className="flex items-center gap-0.5">
                      <button type="button" className={buttonQuiet} disabled={busy} onClick={() => onEdit(item.item_id)} aria-label={`Edit ${item.item_id}`}>
                        <Pencil aria-hidden="true" className="h-3.5 w-3.5" />
                      </button>
                      <button type="button" className={buttonQuietDanger} disabled={busy} onClick={() => setConfirming(item.item_id)} aria-label={`Delete ${item.item_id}`}>
                        <Trash2 aria-hidden="true" className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * One dataset (PRD §26, §42): its questions in the chosen version, the
 * version history with what changed and the problems found, and every edit
 * — add, edit or delete a question, import, change the documents searched —
 * saved as a new version. Older versions are read-only.
 */
const DatasetEditor: React.FC<DatasetEditorProps> = ({ datasetId, documents, onBack, onChanged, onDeleted, onLaunch }) => {
  const [viewVersion, setViewVersion] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>({ kind: "items" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ title: string; error: ApiRequestError } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { dataset, items, version, error: loadError, loaded, refresh } = useDataset(datasetId, viewVersion);

  const latest = dataset?.version ?? null;
  const isLatest = !!latest && (viewVersion == null || viewVersion === latest.number);
  const titleFor = (id: number) => documents.find((document) => document.id === id)?.title ?? null;

  const run = async (title: string, work: () => Promise<string | null>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const message = await work();
      setMode({ kind: "items" });
      setViewVersion(null);
      refresh();
      onChanged();
      if (message) setNotice(message);
    } catch (caught) {
      setError({ title, error: toApiError(caught) });
    } finally {
      setBusy(false);
    }
  };

  const saved = (next: DatasetVersion, what: string) =>
    next.number !== latest?.number ? `${what} Saved as version ${next.number}.` : `${what} Nothing changed, so no version was added.`;

  if (!dataset && loadError) {
    return (
      <div className="space-y-2 text-xs">
        <button type="button" className={buttonQuiet} onClick={onBack}>
          <ArrowLeft aria-hidden="true" className="h-3.5 w-3.5" />
          All datasets
        </button>
        <ErrorNotice
          title={loadError.status === 404 ? "This dataset was not found" : "Could not load the dataset"}
          code={loadError.code}
          message={loadError.status === 404 ? "It may have been deleted." : loadError.message}
          actions={
            loadError.status !== 404 ? (
              <button type="button" className={buttonOutline} onClick={refresh}>
                Try again
              </button>
            ) : undefined
          }
        />
      </div>
    );
  }
  if (!dataset || !latest) {
    return (
      <p role="status" className="text-xs text-muted-foreground">
        Loading the dataset…
      </p>
    );
  }

  const shown = version ?? latest;
  const editing = mode.kind === "edit" ? (items.find((item) => item.item_id === mode.itemId) ?? null) : null;
  const conflict = error?.error.code === "version_conflict";
  const editItem = (itemId: string, input: DatasetItemInput) =>
    void run("Could not save the question", async () => {
      const patch: Partial<DatasetItemInput> = { ...input };
      delete patch.item_id;
      const result = await updateDatasetItem(datasetId, itemId, patch, latest.number);
      return saved(result.version, `Saved ${itemId}.`);
    });

  return (
    <div className="space-y-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" className={buttonQuiet} onClick={onBack}>
          <ArrowLeft aria-hidden="true" className="h-3.5 w-3.5" />
          All datasets
        </button>
        <div className="flex flex-wrap items-center gap-1">
          <button type="button" className={buttonQuiet} onClick={() => void exportDataset(datasetId, "json", shown.number).catch((caught) => setError({ title: "Could not export the dataset", error: toApiError(caught) }))}>
            <Download aria-hidden="true" className="h-3.5 w-3.5" />
            JSON
          </button>
          <button type="button" className={buttonQuiet} onClick={() => void exportDataset(datasetId, "csv", shown.number).catch((caught) => setError({ title: "Could not export the dataset", error: toApiError(caught) }))}>
            <Download aria-hidden="true" className="h-3.5 w-3.5" />
            CSV
          </button>
          <button type="button" className={buttonPrimary} disabled={shown.item_count === 0} onClick={() => onLaunch(datasetId, shown.number)}>
            <FlaskConical aria-hidden="true" className="h-3.5 w-3.5" />
            Run an experiment
          </button>
        </div>
      </div>

      <header>
        <div className="flex flex-wrap items-baseline gap-2">
          <h3 className="text-sm font-medium">{dataset.name}</h3>
          <button type="button" className={buttonQuiet} onClick={() => setMode({ kind: "rename" })} aria-label="Rename the dataset">
            <Pencil aria-hidden="true" className="h-3 w-3" />
          </button>
        </div>
        {dataset.description && <p className="mt-0.5 text-muted-foreground">{dataset.description}</p>}
      </header>

      {mode.kind === "rename" && (
        <RenameForm
          name={dataset.name}
          description={dataset.description}
          busy={busy}
          onCancel={() => setMode({ kind: "items" })}
          onSave={(name, description) =>
            void run("Could not rename the dataset", async () => {
              await updateDataset(datasetId, { name, description });
              return "Renamed (no new version).";
            })
          }
        />
      )}

      <section aria-labelledby="dataset-version-title" className="space-y-1.5 border-y border-border py-2">
        <div className="flex flex-wrap items-center gap-2">
          <h4 id="dataset-version-title" className={eyebrow}>
            Version
          </h4>
          <label htmlFor="dataset-version-select" className="sr-only">
            Version shown
          </label>
          <select
            id="dataset-version-select"
            className={`${inputSmall} text-xs`}
            value={viewVersion ?? latest.number}
            onChange={(event) => {
              const next = Number(event.target.value);
              setMode({ kind: "items" });
              setViewVersion(next === latest.number ? null : next);
            }}
          >
            {dataset.versions.map((ref) => (
              <option key={ref.id} value={ref.number}>
                v{ref.number} · {ref.item_count} {ref.item_count === 1 ? "question" : "questions"}
                {ref.note ? ` · ${ref.note}` : ""}
                {ref.number === latest.number ? " (latest)" : ""}
              </option>
            ))}
          </select>
          {!loaded && <span className="text-[11px] text-muted-foreground">Loading…</span>}
        </div>
        <p className="font-mono text-[11px] text-muted-foreground tabular">
          v{shown.number} · {shown.item_count} {shown.item_count === 1 ? "question" : "questions"} · hash {shown.content_hash.slice(0, 12)} · {formatDateTime(shown.created_at)}
          {shown.note ? ` · ${shown.note}` : ""}
        </p>
        <p className="text-[11px] text-muted-foreground">
          Documents searched:{" "}
          {shown.document_ids.length === 0 ? "every READY document of the workspace" : shown.document_ids.map((id) => titleFor(id) ?? `Document ${id}`).join(", ")}
          {isLatest && (
            <button type="button" className={`${buttonQuiet} ml-1`} onClick={() => setMode({ kind: "corpus" })}>
              Change
            </button>
          )}
        </p>
        <ChecksSummary version={shown} />
        {!isLatest && (
          <p className="text-[11px] text-muted-foreground">
            Version {shown.number} is read-only.{" "}
            <button type="button" className="link" onClick={() => setViewVersion(null)}>
              Show the latest version
            </button>{" "}
            to edit.
          </p>
        )}
      </section>

      {mode.kind === "corpus" && (
        <CorpusEditor
          documents={documents}
          selected={latest.document_ids}
          busy={busy}
          onCancel={() => setMode({ kind: "items" })}
          onSave={(ids) =>
            void run("Could not change the documents", async () => {
              const result = await updateDataset(datasetId, { document_ids: ids, base_version: latest.number });
              return saved(result.version, "Documents changed.");
            })
          }
        />
      )}

      {error && (
        <ApiErrorNotice
          title={conflict ? "Someone changed this dataset meanwhile" : error.title}
          error={error.error}
          actions={
            conflict ? (
              <button
                type="button"
                className={buttonOutline}
                onClick={() => {
                  setError(null);
                  setViewVersion(null);
                  refresh();
                }}
              >
                Load the latest version
              </button>
            ) : undefined
          }
        />
      )}
      {notice && (
        <p role="status" className="border-l-2 border-status-success pl-2 text-foreground">
          {notice}
        </p>
      )}

      {isLatest && mode.kind === "items" && (
        <div className="flex flex-wrap gap-1">
          <button type="button" className={buttonOutline} onClick={() => setMode({ kind: "add" })}>
            <Plus aria-hidden="true" className="h-3.5 w-3.5" />
            Add a question
          </button>
          <button type="button" className={buttonOutline} onClick={() => setMode({ kind: "import" })}>
            <Upload aria-hidden="true" className="h-3.5 w-3.5" />
            Import items
          </button>
          <button type="button" className={`${buttonQuietDanger} ml-auto`} onClick={() => setMode({ kind: "confirm-delete" })}>
            <Trash2 aria-hidden="true" className="h-3.5 w-3.5" />
            Delete dataset
          </button>
        </div>
      )}

      {mode.kind === "confirm-delete" && (
        <div role="alertdialog" aria-labelledby="dataset-delete-title" className="space-y-2 border border-destructive/40 p-3">
          <p id="dataset-delete-title" className="font-medium">
            Delete “{dataset.name}” and all {dataset.version_count} versions?
          </p>
          <p className="text-muted-foreground">Experiments run on it are kept with their own copy of the questions.</p>
          <div className="flex gap-2">
            <button
              type="button"
              className={buttonDanger}
              disabled={busy}
              onClick={() =>
                void (async () => {
                  setBusy(true);
                  try {
                    await deleteDataset(datasetId);
                    onDeleted(datasetId);
                  } catch (caught) {
                    setError({ title: "Could not delete the dataset", error: toApiError(caught) });
                    setBusy(false);
                  }
                })()
              }
            >
              Delete
            </button>
            <button type="button" className={buttonOutline} onClick={() => setMode({ kind: "items" })} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {mode.kind === "add" && (
        <section className="border border-border p-3" aria-label="New question">
          <ItemForm
            idPrefix={`dataset-${datasetId}-new`}
            documents={documents}
            submitLabel="Add the question"
            busy={busy}
            onCancel={() => setMode({ kind: "items" })}
            onSubmit={(input) =>
              void run("Could not add the question", async () => {
                const result = await addDatasetItems(datasetId, [input], latest.number);
                const added = result.items?.[0]?.item_id ?? "the question";
                return saved(result.version, `Added ${added}.`);
              })
            }
          />
        </section>
      )}
      {mode.kind === "edit" && editing && (
        <section className="border border-border p-3" aria-label={`Edit ${editing.item_id}`}>
          <p className="mb-2 font-medium">Editing {editing.item_id}</p>
          <ItemForm
            key={editing.item_id}
            idPrefix={`dataset-${datasetId}-edit`}
            documents={documents}
            initial={editing}
            editing
            submitLabel="Save as a new version"
            busy={busy}
            onCancel={() => setMode({ kind: "items" })}
            onSubmit={(input) => editItem(editing.item_id, input)}
          />
        </section>
      )}
      {mode.kind === "import" && (
        <ImportPanel
          idPrefix={`dataset-${datasetId}`}
          target={{ kind: "existing", datasetId, baseVersion: latest.number }}
          onCancel={() => setMode({ kind: "items" })}
          onDone={(result) => {
            setMode({ kind: "items" });
            setViewVersion(null);
            refresh();
            onChanged();
            setNotice(`Imported ${result.imported} ${result.imported === 1 ? "question" : "questions"}${result.version ? ` · version ${result.version.number}` : ""}.`);
          }}
        />
      )}

      <ItemsTable
        items={items}
        editable={isLatest && mode.kind === "items"}
        busy={busy}
        titleFor={titleFor}
        onEdit={(itemId) => setMode({ kind: "edit", itemId })}
        onDelete={(itemId) =>
          void run("Could not delete the question", async () => {
            const result = await deleteDatasetItem(datasetId, itemId);
            return saved(result.version, `Deleted ${itemId}.`);
          })
        }
      />
    </div>
  );
};

export default DatasetEditor;
