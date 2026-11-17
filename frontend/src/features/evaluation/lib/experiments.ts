import { formatMs } from "../../runs/lib/runMetrics.ts";
import type { Experiment, ExperimentDatasetRef, ExperimentPipelineRef, ExperimentProgress, ExperimentStatus } from "../types/index.ts";
import { formatMetric, metricLabel } from "./metrics.ts";

/**
 * The experiment registry (PRD §29): status wording, which actions a status
 * allows (start, resume, cancel, rerun), progress, headline metrics, the
 * launcher's input checks and the comparison selection.
 */

export const POLL_MS = 2000;
export const MAX_COMPARE = 6;
export const DEFAULT_SEED = 42;
export const DEFAULT_K_VALUES: readonly number[] = [1, 3, 5, 10];
export const SEED_MAX = 2 ** 31 - 1;

const STATUS_LABELS: Record<ExperimentStatus, string> = {
  draft: "Draft",
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status as ExperimentStatus] ?? status;
}

/** Queued or running: the worker may still change it, so it is polled. */
export function isActive(status: string | null | undefined): boolean {
  return status === "queued" || status === "running";
}

export interface ExperimentActions {
  /** First start of a draft. */
  start: boolean;
  /** Queue a failed or cancelled run again; completed items are kept. */
  resume: boolean;
  cancel: boolean;
  /** A new experiment with the same stored configuration. */
  rerun: boolean;
}

export function experimentActions(status: string): ExperimentActions {
  return {
    start: status === "draft",
    resume: status === "failed" || status === "cancelled",
    cancel: status === "queued" || status === "running",
    rerun: status === "completed" || status === "failed" || status === "cancelled",
  };
}

/** Share of items processed (completed or failed), 0–1. */
export function progressFraction(progress: ExperimentProgress | null | undefined): number {
  if (!progress || !(progress.total > 0)) return 0;
  return Math.min(1, Math.max(0, (progress.completed + progress.failed) / progress.total));
}

/** "5 of 20 questions · 1 failed". */
export function progressText(progress: ExperimentProgress | null | undefined): string {
  if (!progress || !(progress.total >= 0)) return "";
  const done = progress.completed + progress.failed;
  const noun = progress.total === 1 ? "question" : "questions";
  const failed = progress.failed > 0 ? ` · ${progress.failed} failed` : "";
  return `${done} of ${progress.total} ${noun}${failed}`;
}

export function datasetLabel(dataset: ExperimentDatasetRef | null | undefined): string {
  if (!dataset) return "—";
  const name = dataset.name || "Deleted dataset";
  return dataset.version != null ? `${name} v${dataset.version}` : name;
}

export function pipelineLabel(pipeline: ExperimentPipelineRef | null | undefined): string {
  if (!pipeline) return "—";
  const name = pipeline.name || "Deleted pipeline";
  return pipeline.version != null ? `${name} v${pipeline.version}` : name;
}

export function experimentLabel(experiment: Pick<Experiment, "id" | "name">): string {
  return `#${experiment.id} ${experiment.name || "Untitled experiment"}`;
}

export function runtimeText(ms: number | null | undefined): string {
  return formatMs(ms);
}

export interface Headline {
  key: string;
  label: string;
  value: string;
}

/** The registry's columns: Recall@5 (or the largest K under it), MRR, nDCG@5, faithfulness. */
export function headlineMetrics(experiment: Pick<Experiment, "metrics" | "k_values" | "retrieval_only">): Headline[] {
  const ks = [...(experiment.k_values ?? [])].sort((a, b) => a - b);
  const k = ks.includes(5) ? 5 : (ks.filter((value) => value <= 5).pop() ?? ks[0] ?? null);
  const retrieval = experiment.metrics?.retrieval ?? {};
  const generation = experiment.metrics?.generation ?? {};
  const keys: { key: string; group: "retrieval" | "generation" }[] = [];
  if (k != null) keys.push({ key: `recall@${k}`, group: "retrieval" });
  keys.push({ key: "mrr", group: "retrieval" });
  if (k != null) keys.push({ key: `ndcg@${k}`, group: "retrieval" });
  if (!experiment.retrieval_only) keys.push({ key: "faithfulness", group: "generation" });
  return keys.map(({ key, group }) => {
    const aggregate = group === "retrieval" ? retrieval[key] : generation[key];
    return { key, label: metricLabel(key), value: formatMetric(aggregate?.mean ?? null) };
  });
}

const WARNING_TITLES: Record<string, string> = {
  repeated_dataset_runs: "Many runs on one test set",
  pipeline_version_missing: "Pipeline version deleted",
  pipeline_version_differs: "Pipeline version changed",
  dataset_version_missing: "Dataset version deleted",
  document_missing: "Document deleted",
  index_version_missing: "Index version deleted",
  index_version_changed: "Document re-indexed since",
  index_changed_during_run: "Re-indexed during the run",
  dataset_version_mismatch: "Different dataset versions",
  evaluation_settings_differ: "Different evaluation settings",
  multiple_changes: "Several settings changed at once",
  index_versions_differ: "Different index versions",
  incomplete_experiment: "Incomplete experiment",
};

export function warningTitle(code: string): string {
  return WARNING_TITLES[code] ?? code.replace(/_/g, " ");
}

/** "1, 3, 5, 10" → [1, 3, 5, 10]: 1–6 distinct whole numbers in 1–50, sorted. */
export function parseKValues(text: string): { values: number[]; error: string | null } {
  const parts = text
    .split(/[\s,;]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length === 0) return { values: [], error: "Enter at least one K, e.g. 1, 3, 5, 10." };
  const values: number[] = [];
  for (const part of parts) {
    if (!/^\d+$/.test(part)) return { values: [], error: `“${part}” is not a whole number.` };
    const value = Number(part);
    if (value < 1 || value > 50) return { values: [], error: "Each K must be between 1 and 50." };
    if (!values.includes(value)) values.push(value);
  }
  if (values.length > 6) return { values: [], error: "At most 6 values of K." };
  return { values: values.sort((a, b) => a - b), error: null };
}

/** A seed field: "" → the default; otherwise a whole number in 0–2³¹−1. */
export function parseSeed(text: string): { value: number; error: string | null } {
  const clean = text.trim();
  if (!clean) return { value: DEFAULT_SEED, error: null };
  if (!/^\d+$/.test(clean)) return { value: DEFAULT_SEED, error: "The seed is a whole number from 0." };
  const value = Number(clean);
  if (value > SEED_MAX) return { value: DEFAULT_SEED, error: `The seed is at most ${SEED_MAX}.` };
  return { value, error: null };
}

/** Toggle an experiment in the comparison selection (at most MAX_COMPARE, order kept). */
export function toggleCompare(selected: readonly number[], id: number): number[] {
  if (selected.includes(id)) return selected.filter((value) => value !== id);
  if (selected.length >= MAX_COMPARE) return [...selected];
  return [...selected, id];
}

/**
 * Experiments can be compared only on the same dataset. Unknown dataset ids
 * (null) are left for the server to judge.
 */
export function sameDataset(experiments: readonly Pick<Experiment, "dataset">[]): boolean {
  const ids = new Set(experiments.map((experiment) => experiment.dataset?.id).filter((id): id is number => id != null));
  return ids.size <= 1;
}
