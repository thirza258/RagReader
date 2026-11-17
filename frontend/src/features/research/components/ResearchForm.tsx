import React, { useState } from "react";
import { buttonOutline, buttonPrimary, eyebrow, inputBase, inputSmall } from "../../../components/ui/classes";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import type { WorkspaceDocument } from "../../documents/types";
import type { PipelinesApi } from "../../pipelines/hooks/usePipelines";
import { createResearchTask } from "../api/research";
import { DEFAULT_DIMENSIONS, KINDS, LIMITS, buildTaskPayload, kindInfo } from "../lib/research";
import type { ResearchKind, ResearchTask } from "../types";

interface ResearchFormProps {
  workspaceId: number;
  documents: readonly WorkspaceDocument[];
  pipelines: PipelinesApi;
  onCreated: (task: ResearchTask, warning: ApiRequestError | null) => void;
  onCancel: () => void;
}

function detailLines(error: ApiRequestError): string[] {
  const details = error.details;
  if (!details || typeof details !== "object") return [];
  return Object.entries(details as Record<string, unknown>).flatMap(([field, messages]) =>
    (Array.isArray(messages) ? messages : [messages]).map((message) => `${field}: ${String(message)}`));
}

/** A new research task (PRD §22–25, §47): what to do, over which documents, with which pipeline. */
const ResearchForm: React.FC<ResearchFormProps> = ({ workspaceId, documents, pipelines, onCreated, onCancel }) => {
  const [kind, setKind] = useState<ResearchKind>("verify_claim");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [dimensionsText, setDimensionsText] = useState("");
  const [fieldsText, setFieldsText] = useState("");
  const [documentIds, setDocumentIds] = useState<number[]>([]);
  const [pipelineId, setPipelineId] = useState<number | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [serverError, setServerError] = useState<ApiRequestError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const ready = documents.filter((document) => document.status === "READY");
  const info = kindInfo(kind);

  const toggle = (id: number) =>
    setDocumentIds((current) => (current.includes(id) ? current.filter((value) => value !== id) : [...current, id]));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const { payload, errors } = buildTaskPayload({ kind, title, text, dimensionsText, fieldsText, documentIds, pipelineId });
    setProblems(errors);
    setServerError(null);
    if (!payload) return;
    setSubmitting(true);
    try {
      const { task, warning } = await createResearchTask({ ...payload, workspace_id: workspaceId });
      onCreated(task, warning);
    } catch (error) {
      setServerError(toApiError(error));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4 border-b border-border p-4" aria-label="New research task">
      <fieldset>
        <legend className={eyebrow}>What should it do?</legend>
        <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
          {KINDS.map((entry) => (
            <label key={entry.id} className={`flex cursor-pointer gap-2 border p-2 text-sm ${kind === entry.id ? "border-primary bg-accent" : "border-border"}`}>
              <input type="radio" name="research-kind" value={entry.id} checked={kind === entry.id} onChange={() => setKind(entry.id)} className="mt-1" />
              <span>
                <span className="block font-medium">{entry.label}</span>
                <span className="block text-xs text-muted-foreground">{entry.description}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {info.prompt && (
        <div>
          <label htmlFor="research-text" className="text-sm font-medium capitalize">{info.prompt}</label>
          <textarea id="research-text" className={`${inputBase} mt-1 min-h-[4.5rem]`} value={text}
            maxLength={LIMITS[info.prompt]} placeholder={info.placeholder} onChange={(event) => setText(event.target.value)} />
        </div>
      )}

      {kind === "compare" && (
        <div>
          <label htmlFor="research-dimensions" className="text-sm font-medium">Dimensions</label>
          <input id="research-dimensions" className={`${inputBase} mt-1`} value={dimensionsText}
            placeholder={DEFAULT_DIMENSIONS.join(", ")} onChange={(event) => setDimensionsText(event.target.value)} />
          <p className="mt-1 text-xs text-muted-foreground">Comma-separated. Leave empty for the defaults shown.</p>
        </div>
      )}

      {kind === "extract" && (
        <div>
          <label htmlFor="research-fields" className="text-sm font-medium">Fields</label>
          <textarea id="research-fields" className={`${inputBase} mt-1 min-h-[6rem] font-mono text-xs`} value={fieldsText}
            placeholder={"dataset: text — the evaluation dataset\nsamples: number — number of samples\nmetrics: list"}
            onChange={(event) => setFieldsText(event.target.value)} />
          <p className="mt-1 text-xs text-muted-foreground">One per line: <code>name: type — description</code>. Types: text, number, list, boolean.</p>
        </div>
      )}

      <fieldset>
        <legend className="text-sm font-medium">Documents</legend>
        <p className="text-xs text-muted-foreground">
          {kind === "compare" ? `Choose ${LIMITS.compareMin}–${LIMITS.compareMax}.` : "None ticked means every READY document."}
        </p>
        {ready.length === 0 ? (
          <p className="mt-1 text-sm text-muted-foreground">No READY documents yet.</p>
        ) : (
          <ul className="mt-1 max-h-40 space-y-1 overflow-y-auto">
            {ready.map((document) => (
              <li key={document.id}>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={documentIds.includes(document.id)} onChange={() => toggle(document.id)} />
                  <span className="truncate" title={document.title}>{document.title}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="research-pipeline" className="text-sm font-medium">Pipeline</label>
          <select id="research-pipeline" className={`${inputSmall} mt-1 w-full`} value={pipelineId ?? ""}
            onChange={(event) => setPipelineId(event.target.value ? Number(event.target.value) : null)}>
            <option value="">Workspace default</option>
            {pipelines.list.map((pipeline) => (
              <option key={pipeline.id} value={pipeline.id}>{pipeline.name}{pipeline.is_default ? " (default)" : ""}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="research-title" className="text-sm font-medium">Title <span className="text-muted-foreground">(optional)</span></label>
          <input id="research-title" className={`${inputSmall} mt-1 w-full`} value={title} maxLength={LIMITS.title}
            onChange={(event) => setTitle(event.target.value)} />
        </div>
      </div>

      {problems.length > 0 && (
        <ul role="alert" className="list-disc space-y-0.5 pl-5 text-sm text-destructive">
          {problems.map((problem) => <li key={problem}>{problem}</li>)}
        </ul>
      )}
      {serverError && (
        <ErrorNotice title="The task was not created" code={serverError.code} message={serverError.message}>
          {detailLines(serverError).map((line) => <p key={line} className="mt-1 text-xs">{line}</p>)}
        </ErrorNotice>
      )}

      <div className="flex gap-2">
        <button type="submit" className={buttonPrimary} disabled={submitting}>{submitting ? "Starting…" : "Start research"}</button>
        <button type="button" className={buttonOutline} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
};

export default ResearchForm;
