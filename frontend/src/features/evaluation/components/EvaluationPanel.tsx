import React, { useState } from "react";
import { focusRing } from "../../../components/ui/classes";
import type { Evidence } from "../../chat/types";
import type { WorkspaceDocument } from "../../documents/types";
import type { PipelinesApi } from "../../pipelines/hooks/usePipelines";
import { useDatasets } from "../hooks/useDatasets";
import { useExperiments } from "../hooks/useExperiments";
import { toggleCompare } from "../lib/experiments";
import ComparisonView from "./ComparisonView";
import DatasetEditor from "./DatasetEditor";
import DatasetList from "./DatasetList";
import ExperimentDetail from "./ExperimentDetail";
import ExperimentLauncher, { type LaunchPreset } from "./ExperimentLauncher";
import ExperimentList from "./ExperimentList";

type Tab = "datasets" | "experiments" | "compare";

const TABS: { id: Tab; label: string }[] = [
  { id: "datasets", label: "Datasets" },
  { id: "experiments", label: "Experiments" },
  { id: "compare", label: "Compare" },
];

interface EvaluationPanelProps {
  workspaceId: number;
  documents: readonly WorkspaceDocument[];
  pipelines: PipelinesApi;
  /** Bumped when a chat answer was added to a dataset, so the list re-reads. */
  datasetsVersion: number;
  /** Opens a retrieved passage of an item's run in the reader. */
  onOpenCandidate: (evidence: Evidence) => void;
}

/**
 * The evaluation lab (PRD §26–31): datasets of questions with expected
 * evidence, experiments that run a dataset version through a pipeline
 * version, and their comparison.
 */
const EvaluationPanel: React.FC<EvaluationPanelProps> = ({ workspaceId, documents, pipelines, datasetsVersion, onOpenCandidate }) => {
  const [tab, setTab] = useState<Tab>("datasets");
  const [datasetId, setDatasetId] = useState<number | null>(null);
  const [experimentId, setExperimentId] = useState<number | null>(null);
  const [launch, setLaunch] = useState<LaunchPreset | null>(null);
  const [compareIds, setCompareIds] = useState<number[]>([]);
  const [experimentsVersion, setExperimentsVersion] = useState(0);
  const datasets = useDatasets(workspaceId, datasetsVersion);
  const experiments = useExperiments(workspaceId, experimentsVersion);
  const documentTitle = (id: number) => documents.find((document) => document.id === id)?.title ?? null;

  const onTabKeyDown = (event: React.KeyboardEvent) => {
    const index = TABS.findIndex((item) => item.id === tab);
    const targets: Record<string, number> = { ArrowRight: (index + 1) % TABS.length, ArrowLeft: (index - 1 + TABS.length) % TABS.length, Home: 0, End: TABS.length - 1 };
    const next = targets[event.key];
    if (next === undefined) return;
    event.preventDefault();
    setTab(TABS[next].id);
    window.document.getElementById(`evaluation-tab-${TABS[next].id}`)?.focus();
  };

  const openExperiment = (id: number) => {
    setLaunch(null);
    setExperimentId(id);
    setTab("experiments");
  };
  const refreshExperiments = () => setExperimentsVersion((value) => value + 1);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div role="tablist" aria-label="Evaluation" className="flex shrink-0 gap-1 border-b border-border px-3 pt-1.5" onKeyDown={onTabKeyDown}>
        {TABS.map((item) => (
          <button
            key={item.id}
            id={`evaluation-tab-${item.id}`}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            aria-controls={`evaluation-panel-${item.id}`}
            tabIndex={tab === item.id ? 0 : -1}
            onClick={() => setTab(item.id)}
            className={`border-b-2 px-2 py-1 text-xs transition-colors ${focusRing} ${
              tab === item.id ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {item.label}
            {item.id === "compare" && compareIds.length > 0 ? ` (${compareIds.length})` : ""}
          </button>
        ))}
      </div>
      <div id={`evaluation-panel-${tab}`} role="tabpanel" aria-labelledby={`evaluation-tab-${tab}`} className="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {tab === "datasets" &&
          (datasetId != null ? (
            <DatasetEditor
              key={datasetId}
              datasetId={datasetId}
              documents={documents}
              onBack={() => setDatasetId(null)}
              onChanged={datasets.refresh}
              onDeleted={(id) => {
                datasets.removeLocal(id);
                setDatasetId(null);
              }}
              onLaunch={(id, version) => {
                setLaunch({ datasetId: id, version });
                setExperimentId(null);
                setTab("experiments");
              }}
            />
          ) : (
            <DatasetList workspaceId={workspaceId} datasets={datasets} onOpen={setDatasetId} />
          ))}

        {tab === "experiments" &&
          (launch ? (
            <ExperimentLauncher
              workspaceId={workspaceId}
              datasets={datasets.list}
              pipelines={pipelines}
              preset={launch}
              onCancel={() => setLaunch(null)}
              onCreated={(result) => {
                refreshExperiments();
                datasets.refresh();
                openExperiment(result.experiment.id);
              }}
            />
          ) : experimentId != null ? (
            <ExperimentDetail
              key={experimentId}
              experimentId={experimentId}
              onBack={() => setExperimentId(null)}
              onChanged={refreshExperiments}
              onDeleted={(id) => {
                setCompareIds((ids) => ids.filter((value) => value !== id));
                setExperimentId(null);
                refreshExperiments();
              }}
              onOpenExperiment={openExperiment}
              documentTitle={documentTitle}
              onOpenCandidate={onOpenCandidate}
            />
          ) : (
            <ExperimentList
              experiments={experiments}
              compareIds={compareIds}
              onToggleCompare={(id) => setCompareIds((ids) => toggleCompare(ids, id))}
              onCompare={() => setTab("compare")}
              onOpen={openExperiment}
              onNew={() => setLaunch({ datasetId: null, version: null })}
            />
          ))}

        {tab === "compare" && (
          <ComparisonView
            experiments={experiments.list}
            selectedIds={compareIds}
            onRemove={(id) => setCompareIds((ids) => ids.filter((value) => value !== id))}
            onOpenExperiment={openExperiment}
            onPick={() => {
              setExperimentId(null);
              setLaunch(null);
              setTab("experiments");
            }}
          />
        )}
      </div>
    </div>
  );
};

export default EvaluationPanel;
