import React, { useState } from "react";
import { buttonOutline, buttonPrimary, inputBase, inputSmall } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import type { PipelinesApi } from "../../pipelines/hooks/usePipelines";
import { describeConfig } from "../../pipelines/lib/pipelineConfig";
import { createExperiment, type StartResult } from "../api/evaluation";
import { DEFAULT_K_VALUES, DEFAULT_SEED, parseKValues, parseSeed } from "../lib/experiments";
import type { Dataset } from "../types";
import ApiErrorNotice from "./ApiErrorNotice";

export interface LaunchPreset {
  datasetId: number | null;
  version: number | null;
}

interface ExperimentLauncherProps {
  workspaceId: number;
  datasets: readonly Dataset[];
  pipelines: PipelinesApi;
  preset: LaunchPreset;
  onCancel: () => void;
  onCreated: (result: StartResult) => void;
}

/**
 * A new experiment (PRD §29): one dataset version through one pipeline
 * version, measured with retrieval metrics and — unless retrieval only —
 * the generated answer judged by an LLM. The run happens in the background.
 */
const ExperimentLauncher: React.FC<ExperimentLauncherProps> = ({ workspaceId, datasets, pipelines, preset, onCancel, onCreated }) => {
  // Chosen values; null falls back to the preset or the first/default entry,
  // so lists that arrive after the form opened still give it a choice.
  const [datasetId, setDatasetId] = useState<number | null>(preset.datasetId);
  const [version, setVersion] = useState<number | null>(preset.version);
  const [pipelineId, setPipelineId] = useState<number | null>(null);
  const [pipelineVersionId, setPipelineVersionId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  const [retrievalOnly, setRetrievalOnly] = useState(false);
  const [queryRewrite, setQueryRewrite] = useState(true);
  const [seed, setSeed] = useState(String(DEFAULT_SEED));
  const [kText, setKText] = useState(DEFAULT_K_VALUES.join(", "));
  const [judgeModel, setJudgeModel] = useState("");
  const [draft, setDraft] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiRequestError | null>(null);

  const dataset = datasets.find((item) => item.id === datasetId) ?? datasets[0] ?? null;
  const pipeline = pipelines.list.find((item) => item.id === pipelineId) ?? pipelines.list.find((item) => item.is_default) ?? pipelines.list[0] ?? null;
  const chosenVersion = dataset?.versions.some((ref) => ref.number === version) ? version : null;
  const versionNumber = chosenVersion ?? dataset?.version?.number ?? null;
  const versionRef = dataset?.versions.find((ref) => ref.number === versionNumber) ?? null;
  const pipelineVersion = pipeline?.versions.find((ref) => ref.id === pipelineVersionId) ?? null;
  const shownPipelineVersion = pipelineVersion?.number ?? pipeline?.version?.number ?? null;
  const k = parseKValues(kText);
  const parsedSeed = parseSeed(seed);
  const defaultName = dataset && pipeline ? `${dataset.name} · ${pipeline.name} v${shownPipelineVersion ?? "?"}${retrievalOnly ? " · retrieval only" : ""}` : "";
  const empty = versionRef != null && versionRef.item_count === 0;
  const canSubmit = !!dataset && !!pipeline && !k.error && !parsedSeed.error && !empty && !busy;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit || !dataset || !pipeline) return;
    setBusy(true);
    setError(null);
    try {
      const result = await createExperiment({
        name: name.trim() || defaultName,
        hypothesis: hypothesis.trim(),
        workspace_id: workspaceId,
        dataset_id: dataset.id,
        ...(versionNumber != null ? { dataset_version: versionNumber } : {}),
        ...(pipelineVersionId != null ? { pipeline_version_id: pipelineVersionId } : { pipeline_id: pipeline.id }),
        retrieval_only: retrievalOnly,
        query_rewrite: queryRewrite,
        seed: parsedSeed.value,
        k_values: k.values,
        ...(judgeModel.trim() && !retrievalOnly ? { judge_model: judgeModel.trim() } : {}),
        draft,
      });
      onCreated(result);
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setBusy(false);
    }
  };

  if (datasets.length === 0) {
    return (
      <div className="space-y-2 text-xs">
        <p className="text-muted-foreground">Create a dataset with at least one question first.</p>
        <button type="button" className={buttonOutline} onClick={onCancel}>
          Back
        </button>
      </div>
    );
  }

  return (
    <form className="space-y-3 text-xs" onSubmit={(event) => void submit(event)} noValidate>
      <h3 className="text-sm font-medium">New experiment</h3>
      <div className="grid gap-2 sm:grid-cols-2">
        <label htmlFor="launch-dataset" className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
          Dataset
          <select
            id="launch-dataset"
            className={`${inputSmall} text-xs`}
            value={dataset?.id ?? ""}
            onChange={(event) => {
              setDatasetId(event.target.value ? Number(event.target.value) : null);
              setVersion(null);
            }}
          >
            {datasets.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor="launch-dataset-version" className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
          Dataset version
          <select
            id="launch-dataset-version"
            className={`${inputSmall} text-xs`}
            value={versionNumber ?? ""}
            onChange={(event) => setVersion(event.target.value ? Number(event.target.value) : null)}
          >
            {(dataset?.versions ?? []).map((ref) => (
              <option key={ref.id} value={ref.number}>
                v{ref.number} · {ref.item_count} {ref.item_count === 1 ? "question" : "questions"}
                {ref.number === dataset?.version?.number ? " (latest)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor="launch-pipeline" className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
          Pipeline
          <select
            id="launch-pipeline"
            className={`${inputSmall} text-xs`}
            value={pipeline?.id ?? ""}
            disabled={!pipelines.loaded}
            onChange={(event) => {
              setPipelineId(event.target.value ? Number(event.target.value) : null);
              setPipelineVersionId(null);
            }}
          >
            {pipelines.list.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
                {item.is_default ? " (default)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor="launch-pipeline-version" className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
          Pipeline version
          <select
            id="launch-pipeline-version"
            className={`${inputSmall} text-xs`}
            value={pipelineVersionId ?? ""}
            onChange={(event) => setPipelineVersionId(event.target.value ? Number(event.target.value) : null)}
          >
            <option value="">Latest (v{pipeline?.version?.number ?? "?"})</option>
            {(pipeline?.versions ?? []).map((ref) => (
              <option key={ref.id} value={ref.id}>
                v{ref.number}
              </option>
            ))}
          </select>
        </label>
      </div>
      {pipeline && pipelineVersionId == null && <p className="text-[11px] text-muted-foreground">{describeConfig(pipeline.version.config)}</p>}
      {empty && <p className="text-[11px] text-destructive">This dataset version has no questions.</p>}

      <fieldset className="space-y-1">
        <legend className="sr-only">What to measure</legend>
        <label className="flex items-start gap-2">
          <input type="checkbox" checked={retrievalOnly} onChange={(event) => setRetrievalOnly(event.target.checked)} />
          <span>
            Retrieval only <span className="text-muted-foreground">— no answers are generated or judged (no LLM generation cost); generation metrics are not computed.</span>
          </span>
        </label>
        <label className="flex items-start gap-2">
          <input type="checkbox" checked={queryRewrite} onChange={(event) => setQueryRewrite(event.target.checked)} />
          <span>
            Rewrite follow-up questions <span className="text-muted-foreground">— as chat does, for questions with conversation history.</span>
          </span>
        </label>
      </fieldset>

      <div className="grid gap-2 sm:grid-cols-3">
        <label htmlFor="launch-k" className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
          K values (Recall@K, Precision@K…)
          <input id="launch-k" className={`${inputSmall} font-mono text-xs`} value={kText} onChange={(event) => setKText(event.target.value)} aria-invalid={!!k.error} />
        </label>
        <label htmlFor="launch-seed" className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
          Seed
          <input id="launch-seed" inputMode="numeric" className={`${inputSmall} font-mono text-xs`} value={seed} onChange={(event) => setSeed(event.target.value)} aria-invalid={!!parsedSeed.error} />
        </label>
        <label htmlFor="launch-judge" className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
          Judge model
          <input
            id="launch-judge"
            className={`${inputSmall} font-mono text-xs`}
            value={judgeModel}
            disabled={retrievalOnly}
            placeholder="server default"
            onChange={(event) => setJudgeModel(event.target.value)}
          />
        </label>
      </div>
      {k.error && <p className="text-[11px] text-destructive">{k.error}</p>}
      {parsedSeed.error && <p className="text-[11px] text-destructive">{parsedSeed.error}</p>}

      <label htmlFor="launch-name" className="flex flex-col gap-0.5 font-medium">
        Name
        <input id="launch-name" className={`${inputSmall} text-xs font-normal`} value={name} maxLength={200} placeholder={defaultName} onChange={(event) => setName(event.target.value)} />
      </label>
      <label htmlFor="launch-hypothesis" className="flex flex-col gap-0.5 font-medium">
        Hypothesis <span className="font-normal text-muted-foreground">(what you expect, e.g. “Hybrid retrieval improves Recall@5”)</span>
        <textarea id="launch-hypothesis" rows={2} className={`${inputBase} text-sm font-normal`} value={hypothesis} onChange={(event) => setHypothesis(event.target.value)} />
      </label>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={draft} onChange={(event) => setDraft(event.target.checked)} />
        Save as a draft (start it later)
      </label>

      {error && <ApiErrorNotice title="Could not create the experiment" error={error} />}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={buttonPrimary} disabled={!canSubmit}>
          {busy ? "Creating…" : draft ? "Create draft" : "Start experiment"}
        </button>
        <button type="button" className={buttonOutline} onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
};

export default ExperimentLauncher;
