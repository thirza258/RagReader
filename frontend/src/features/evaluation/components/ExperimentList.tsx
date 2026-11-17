import React from "react";
import { GitCompare, Loader2, Plus, RefreshCw } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonOutline, buttonPrimary, buttonQuiet, focusRing } from "../../../components/ui/classes";
import { formatDateTime } from "../../documents/lib/format";
import type { ExperimentsApi } from "../hooks/useExperiments";
import { MAX_COMPARE, datasetLabel, headlineMetrics, isActive, pipelineLabel, sameDataset } from "../lib/experiments";
import type { Experiment } from "../types";
import ProgressBar from "./ProgressBar";
import StatusBadge from "./StatusBadge";

interface ExperimentListProps {
  experiments: ExperimentsApi;
  compareIds: readonly number[];
  onToggleCompare: (id: number) => void;
  onCompare: () => void;
  onOpen: (id: number) => void;
  onNew: () => void;
}

function ExperimentRow({ experiment, selected, canSelect, onToggle, onOpen }: { experiment: Experiment; selected: boolean; canSelect: boolean; onToggle: () => void; onOpen: () => void }) {
  const headline = headlineMetrics(experiment);
  return (
    <li className="flex items-start gap-2 border-l-2 border-border py-1.5 pl-2">
      <input
        type="checkbox"
        className="mt-1"
        checked={selected}
        disabled={!selected && !canSelect}
        onChange={onToggle}
        aria-label={`Compare #${experiment.id} ${experiment.name}`}
      />
      <button type="button" onClick={onOpen} className={`min-w-0 flex-1 text-left transition-colors hover:bg-accent ${focusRing}`}>
        <span className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="min-w-0 truncate text-sm font-medium text-foreground">
            <span className="font-mono text-[11px] text-muted-foreground">#{experiment.id}</span> {experiment.name}
          </span>
          <StatusBadge status={experiment.status} />
        </span>
        <span className="mt-0.5 block text-[11px] text-muted-foreground">
          {datasetLabel(experiment.dataset)} · {pipelineLabel(experiment.pipeline)}
          {experiment.pipeline?.strategy ? ` (${experiment.pipeline.strategy})` : ""} · {experiment.retrieval_only ? "retrieval only" : "retrieval + generation"} ·{" "}
          {formatDateTime(experiment.created_at)}
        </span>
        {isActive(experiment.status) && <ProgressBar progress={experiment.progress} className="mt-1" />}
        {experiment.metrics && (
          <span className="mt-0.5 flex flex-wrap gap-x-3 font-mono text-[11px] tabular">
            {headline.map((metric) => (
              <span key={metric.key}>
                <span className="text-muted-foreground">{metric.label}</span> {metric.value}
              </span>
            ))}
          </span>
        )}
        {experiment.status === "failed" && experiment.error && (
          <span className="mt-0.5 block text-[11px] text-destructive">
            <span className="font-mono">{experiment.error.code}</span> · {experiment.error.message}
          </span>
        )}
      </button>
    </li>
  );
}

/**
 * The experiment registry (PRD §29): every experiment of the workspace with
 * its status, live progress and headline metrics. Tick 2–6 experiments on
 * the same dataset to compare them (§30).
 */
const ExperimentList: React.FC<ExperimentListProps> = ({ experiments, compareIds, onToggleCompare, onCompare, onOpen, onNew }) => {
  const selected = experiments.list.filter((experiment) => compareIds.includes(experiment.id));
  const comparable = selected.length >= 2 && sameDataset(selected);
  return (
    <div className="space-y-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">Experiments</h3>
        <div className="flex items-center gap-1">
          <button type="button" className={buttonPrimary} onClick={onNew}>
            <Plus aria-hidden="true" className="h-3.5 w-3.5" />
            New experiment
          </button>
          <button type="button" className={buttonQuiet} onClick={experiments.refresh} aria-label="Refresh experiments" disabled={!experiments.loaded}>
            {experiments.loaded ? <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" /> : <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-y border-border py-1.5">
        <span className="text-muted-foreground">
          {compareIds.length === 0 ? `Tick 2–${MAX_COMPARE} experiments on the same dataset to compare them.` : `${compareIds.length} selected for comparison.`}
        </span>
        {selected.length >= 2 && !sameDataset(selected) && <span className="text-destructive">They must use the same dataset.</span>}
        <button type="button" className={`${buttonOutline} ml-auto px-2 py-1 text-xs`} disabled={!comparable} onClick={onCompare}>
          <GitCompare aria-hidden="true" className="h-3.5 w-3.5" />
          Compare
        </button>
      </div>

      {experiments.error && (
        <ErrorNotice
          title="Could not load the experiments"
          code={experiments.error.code}
          message={experiments.error.message}
          actions={
            <button type="button" className={buttonOutline} onClick={experiments.refresh}>
              Try again
            </button>
          }
        />
      )}
      {!experiments.everLoaded && !experiments.error && (
        <p role="status" className="text-muted-foreground">
          Loading experiments…
        </p>
      )}
      {experiments.everLoaded && experiments.list.length === 0 && !experiments.error && (
        <p className="text-muted-foreground">No experiments yet. Run one on a dataset to measure a pipeline version.</p>
      )}
      {experiments.list.length > 0 && (
        <ul className="space-y-1">
          {experiments.list.map((experiment) => (
            <ExperimentRow
              key={experiment.id}
              experiment={experiment}
              selected={compareIds.includes(experiment.id)}
              canSelect={compareIds.length < MAX_COMPARE}
              onToggle={() => onToggleCompare(experiment.id)}
              onOpen={() => onOpen(experiment.id)}
            />
          ))}
        </ul>
      )}
    </div>
  );
};

export default ExperimentList;
