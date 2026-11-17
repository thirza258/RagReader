import React, { useState } from "react";
import { Plus } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonDanger, buttonOutline, buttonQuiet, buttonQuietDanger, eyebrow, inputSmall } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import type { PipelinesApi } from "../hooks/usePipelines";
import { configChanges, describeConfig, pipelineVersionLabel } from "../lib/pipelineConfig";
import type { Pipeline, PipelineConfig } from "../types";
import PipelineForm from "./PipelineForm";
import PipelineHistory from "./PipelineHistory";

type Mode = { kind: "list" } | { kind: "create" } | { kind: "edit"; id: number } | { kind: "history"; id: number } | { kind: "confirm-delete"; id: number };

interface PipelinePanelProps {
  pipelines: PipelinesApi;
  /** The pipeline the open conversation (or the next new one) uses. */
  selectedId: number | null;
  /** Null while no conversation is open: the choice applies to the next one. */
  conversationTitle: string | null;
  onSelect: (id: number) => Promise<void>;
  /** After a delete: conversations that used it now follow the default. */
  onDeleted: () => void;
}

function fieldErrors(error: ApiRequestError | null): Record<string, string[]> | null {
  const details = error?.details;
  return details && typeof details === "object" && !Array.isArray(details) ? (details as Record<string, string[]>) : null;
}

/**
 * Retrieval pipelines (PRD §17–19): choose the conversation's pipeline,
 * create and edit pipelines (an edit that changes a setting adds a version;
 * versions never change) and read each pipeline's version history.
 */
const PipelinePanel: React.FC<PipelinePanelProps> = ({ pipelines, selectedId, conversationTitle, onSelect, onDeleted }) => {
  const [mode, setMode] = useState<Mode>({ kind: "list" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ title: string; error: ApiRequestError } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { list, options } = pipelines;
  const selected = list.find((pipeline) => pipeline.id === selectedId) ?? list.find((pipeline) => pipeline.is_default) ?? null;

  const run = async (title: string, work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await work();
    } catch (caught) {
      setError({ title, error: toApiError(caught) });
    } finally {
      setBusy(false);
    }
  };

  if (!pipelines.loaded) {
    return (
      <p role="status" className="p-3 text-xs text-muted-foreground">
        Loading pipelines…
      </p>
    );
  }
  if (pipelines.error && list.length === 0) {
    return (
      <div className="p-3">
        <ErrorNotice
          title="Could not load the pipelines"
          code={pipelines.error.code}
          message={pipelines.error.message}
          actions={
            <button type="button" className={buttonOutline} onClick={pipelines.refresh}>
              Try again
            </button>
          }
        />
      </div>
    );
  }

  const editing = mode.kind === "edit" ? list.find((pipeline) => pipeline.id === mode.id) ?? null : null;
  const submitCreate = (name: string, config: PipelineConfig) =>
    void run("Could not create the pipeline", async () => {
      const created = await pipelines.create(name, config);
      setMode({ kind: "list" });
      setNotice(`Created “${created.name}” (v1).`);
    });
  const submitEdit = (pipeline: Pipeline) => (name: string, config: PipelineConfig) =>
    void run("Could not save the pipeline", async () => {
      const changes = configChanges(pipeline.version.config, config);
      const saved = await pipelines.update(pipeline.id, {
        ...(name !== pipeline.name ? { name } : {}),
        ...(Object.keys(changes).length > 0 ? { config: changes } : {}),
      });
      setMode({ kind: "list" });
      setNotice(saved.version_created ? `Saved as v${saved.version.number}. New questions use it; earlier answers keep their version.` : `No setting changed; still v${saved.version.number}.`);
    });

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 text-xs custom-scrollbar">
      <section aria-labelledby="pipeline-choice">
        <h3 id="pipeline-choice" className="text-sm font-medium">
          {conversationTitle ? "This conversation's pipeline" : "Pipeline for the next conversation"}
        </h3>
        {conversationTitle && <p className="mt-0.5 truncate text-muted-foreground">{conversationTitle}</p>}
        <div className="mt-1.5 flex items-center gap-2">
          <label htmlFor="pipeline-select" className="sr-only">
            Pipeline
          </label>
          <select
            id="pipeline-select"
            className={`${inputSmall} min-w-0 flex-1`}
            value={selected?.id ?? ""}
            disabled={busy || list.length === 0}
            onChange={(event) => void run("Could not switch the pipeline", () => onSelect(Number(event.target.value)))}
          >
            {list.map((pipeline) => (
              <option key={pipeline.id} value={pipeline.id}>
                {pipelineVersionLabel({ name: pipeline.name, number: pipeline.version.number })}
                {pipeline.is_default ? " (default)" : ""}
              </option>
            ))}
          </select>
        </div>
        {selected && <p className="mt-1 text-muted-foreground">{describeConfig(selected.version.config)}</p>}
        <p className="mt-1 text-[11px] text-muted-foreground">Each question uses the pipeline's latest version at the time it is asked.</p>
      </section>

      {error && (
        <ErrorNotice className="mt-3" title={error.title} code={error.error.code} message={error.error.message}>
          {fieldErrors(error.error) && (
            <ul className="mt-1 list-disc pl-4 text-[11px]">
              {Object.entries(fieldErrors(error.error) ?? {}).map(([field, messages]) => (
                <li key={field}>
                  <span className="font-mono">{field}</span>: {Array.isArray(messages) ? messages.join(" ") : String(messages)}
                </li>
              ))}
            </ul>
          )}
        </ErrorNotice>
      )}
      {notice && (
        <p role="status" className="mt-3 border-l-2 border-status-success pl-2 text-foreground">
          {notice}
        </p>
      )}

      <section className="mt-4" aria-labelledby="pipeline-list">
        <div className="flex items-center justify-between gap-2">
          <h3 id="pipeline-list" className="text-sm font-medium">
            Pipelines
          </h3>
          {mode.kind !== "create" && options && (
            <button type="button" className={`${buttonOutline} px-2 py-1 text-xs`} disabled={busy} onClick={() => setMode({ kind: "create" })}>
              <Plus aria-hidden="true" className="h-3.5 w-3.5" />
              New pipeline
            </button>
          )}
        </div>

        {mode.kind === "create" && options && (
          <div className="mt-2 border border-border p-2">
            <p className={eyebrow}>New pipeline</p>
            <PipelineForm
              options={options}
              initialName=""
              initialConfig={selected?.version.config ?? options.defaults}
              submitLabel="Create"
              busy={busy}
              serverErrors={fieldErrors(error?.error ?? null)}
              onSubmit={submitCreate}
              onCancel={() => setMode({ kind: "list" })}
            />
          </div>
        )}

        <ul className="mt-2 space-y-2">
          {list.map((pipeline) => (
            <li key={pipeline.id} className="border border-border p-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="font-medium">
                  {pipeline.name} <span className="font-mono text-muted-foreground">v{pipeline.version.number}</span>
                  {pipeline.is_default && <span className="ml-1.5 text-[11px] font-normal text-muted-foreground">default</span>}
                </p>
                <span className="text-[11px] text-muted-foreground">
                  {pipeline.version_count} version{pipeline.version_count === 1 ? "" : "s"}
                </span>
              </div>
              <p className="mt-0.5 text-muted-foreground">{describeConfig(pipeline.version.config)}</p>

              {editing?.id === pipeline.id && options ? (
                <div className="mt-2 border-t border-border pt-2">
                  <PipelineForm
                    key={pipeline.version.id}
                    options={options}
                    initialName={pipeline.name}
                    initialConfig={pipeline.version.config}
                    submitLabel="Save as a new version"
                    busy={busy}
                    serverErrors={fieldErrors(error?.error ?? null)}
                    onSubmit={submitEdit(pipeline)}
                    onCancel={() => setMode({ kind: "list" })}
                  />
                </div>
              ) : mode.kind === "confirm-delete" && mode.id === pipeline.id ? (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <span>Delete “{pipeline.name}”? Conversations using it switch to the default; recorded runs keep its configuration.</span>
                  <button
                    type="button"
                    className={`${buttonDanger} px-2 py-1 text-xs`}
                    disabled={busy}
                    onClick={() =>
                      void run("Could not delete the pipeline", async () => {
                        await pipelines.remove(pipeline.id);
                        setMode({ kind: "list" });
                        onDeleted();
                      })
                    }
                  >
                    Delete
                  </button>
                  <button type="button" className={`${buttonOutline} px-2 py-1 text-xs`} onClick={() => setMode({ kind: "list" })}>
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="mt-1 flex flex-wrap gap-1">
                  <button type="button" className={buttonQuiet} disabled={busy || !options} onClick={() => setMode({ kind: "edit", id: pipeline.id })}>
                    Edit
                  </button>
                  <button
                    type="button"
                    className={buttonQuiet}
                    aria-expanded={mode.kind === "history" && mode.id === pipeline.id}
                    onClick={() => setMode(mode.kind === "history" && mode.id === pipeline.id ? { kind: "list" } : { kind: "history", id: pipeline.id })}
                  >
                    {mode.kind === "history" && mode.id === pipeline.id ? "Hide history" : "History"}
                  </button>
                  {!pipeline.is_default && (
                    <button type="button" className={buttonQuietDanger} disabled={busy} onClick={() => setMode({ kind: "confirm-delete", id: pipeline.id })}>
                      Delete
                    </button>
                  )}
                </div>
              )}
              {mode.kind === "history" && mode.id === pipeline.id && (
                <div className="mt-2 border-t border-border pt-2">
                  <PipelineHistory pipelineId={pipeline.id} latestVersionId={pipeline.version.id} />
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
};

export default PipelinePanel;
