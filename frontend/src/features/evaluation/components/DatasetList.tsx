import React, { useState } from "react";
import { Loader2, Plus, RefreshCw, Upload } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonOutline, buttonPrimary, buttonQuiet, focusRing, inputSmall } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import { formatDateTime } from "../../documents/lib/format";
import { createDataset } from "../api/evaluation";
import type { DatasetsApi } from "../hooks/useDatasets";
import type { Dataset } from "../types";
import ApiErrorNotice from "./ApiErrorNotice";
import ImportPanel from "./ImportPanel";

interface DatasetListProps {
  workspaceId: number;
  datasets: DatasetsApi;
  onOpen: (id: number) => void;
}

function DatasetRow({ dataset, onOpen }: { dataset: Dataset; onOpen: (id: number) => void }) {
  return (
    <li>
      <button type="button" onClick={() => onOpen(dataset.id)} className={`block w-full border-l-2 border-border px-2.5 py-1.5 text-left transition-colors hover:bg-accent ${focusRing}`}>
        <span className="flex items-baseline justify-between gap-2">
          <span className="truncate text-sm font-medium text-foreground">{dataset.name}</span>
          <span className="shrink-0 font-mono text-[11px] text-muted-foreground">v{dataset.version?.number ?? "?"}</span>
        </span>
        <span className="mt-0.5 block text-[11px] text-muted-foreground tabular">
          {dataset.version?.item_count ?? 0} {dataset.version?.item_count === 1 ? "question" : "questions"} · {dataset.version_count}{" "}
          {dataset.version_count === 1 ? "version" : "versions"} · {dataset.experiment_count} {dataset.experiment_count === 1 ? "experiment" : "experiments"} · updated{" "}
          {formatDateTime(dataset.updated_at)}
        </span>
        {dataset.description && <span className="mt-0.5 line-clamp-2 block text-[11px] text-muted-foreground">{dataset.description}</span>}
      </button>
    </li>
  );
}

/**
 * The workspace's evaluation datasets (PRD §26): open one to edit its
 * questions, create an empty one, or import one from a JSON or CSV file.
 */
const DatasetList: React.FC<DatasetListProps> = ({ workspaceId, datasets, onOpen }) => {
  const [mode, setMode] = useState<"list" | "create" | "import">("list");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiRequestError | null>(null);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const dataset = await createDataset({ workspaceId, name: name.trim(), description: description.trim() });
      datasets.store(dataset);
      setName("");
      setDescription("");
      setMode("list");
      onOpen(dataset.id);
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">Datasets</h3>
        <div className="flex items-center gap-1">
          <button type="button" className={buttonQuiet} onClick={() => setMode(mode === "create" ? "list" : "create")}>
            <Plus aria-hidden="true" className="h-3.5 w-3.5" />
            New dataset
          </button>
          <button type="button" className={buttonQuiet} onClick={() => setMode(mode === "import" ? "list" : "import")}>
            <Upload aria-hidden="true" className="h-3.5 w-3.5" />
            Import
          </button>
          <button type="button" className={buttonQuiet} onClick={datasets.refresh} aria-label="Refresh datasets" disabled={!datasets.loaded}>
            {datasets.loaded ? <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" /> : <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />}
          </button>
        </div>
      </div>
      <p className="text-muted-foreground">
        A dataset is a list of questions with their expected sources and, optionally, expected answers. Every edit saves a new, immutable version, so an experiment
        always names exactly what it was measured on.
      </p>

      {mode === "create" && (
        <form className="space-y-2 border border-border p-3" onSubmit={(event) => void create(event)}>
          <label htmlFor="dataset-new-name" className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
            Name
            <input id="dataset-new-name" className={`${inputSmall} text-xs`} value={name} maxLength={120} required onChange={(event) => setName(event.target.value)} />
          </label>
          <label htmlFor="dataset-new-description" className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
            Description (optional)
            <textarea id="dataset-new-description" rows={2} className={`${inputSmall} text-xs`} value={description} maxLength={2000} onChange={(event) => setDescription(event.target.value)} />
          </label>
          {error && <ApiErrorNotice title="Could not create the dataset" error={error} />}
          <div className="flex gap-2">
            <button type="submit" className={buttonPrimary} disabled={busy || !name.trim()}>
              Create
            </button>
            <button type="button" className={buttonOutline} onClick={() => setMode("list")} disabled={busy}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {mode === "import" && (
        <ImportPanel
          idPrefix="dataset-new"
          target={{ kind: "new", workspaceId }}
          onCancel={() => setMode("list")}
          onDone={(result) => {
            setMode("list");
            if (result.dataset) {
              datasets.store(result.dataset);
              onOpen(result.dataset.id);
            } else {
              datasets.refresh();
            }
          }}
        />
      )}

      {datasets.error && (
        <ErrorNotice
          title="Could not load the datasets"
          code={datasets.error.code}
          message={datasets.error.message}
          actions={
            <button type="button" className={buttonOutline} onClick={datasets.refresh}>
              Try again
            </button>
          }
        />
      )}
      {!datasets.everLoaded && !datasets.error && (
        <p role="status" className="text-muted-foreground">
          Loading datasets…
        </p>
      )}
      {datasets.everLoaded && datasets.list.length === 0 && !datasets.error && (
        <p className="text-muted-foreground">No datasets yet. Create one, import a file, or use “Add to dataset” on a chat answer.</p>
      )}
      {datasets.list.length > 0 && (
        <ul className="space-y-1">
          {datasets.list.map((dataset) => (
            <DatasetRow key={dataset.id} dataset={dataset} onOpen={onOpen} />
          ))}
        </ul>
      )}
    </div>
  );
};

export default DatasetList;
