import React, { useState } from "react";
import { buttonPrimary, eyebrow, focusRing } from "../../../components/ui/classes";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import type { ApiRequestError } from "../../../services/api/errors";
import type { Evidence } from "../../chat/types";
import type { WorkspaceDocument } from "../../documents/types";
import type { PipelinesApi } from "../../pipelines/hooks/usePipelines";
import { useResearchTasks } from "../hooks/useResearch";
import { statusLabel } from "../lib/research";
import ResearchForm from "./ResearchForm";
import ResearchResult from "./ResearchResult";

interface ResearchPanelProps {
  workspaceId: number;
  documents: readonly WorkspaceDocument[];
  pipelines: PipelinesApi;
  /** Opens a passage of a task's evidence in the reader. */
  onOpenEvidence: (evidence: Evidence) => void;
}

/** The workspace's research desk (PRD §22–25, §47): start tasks, follow them, read their evidence. */
const ResearchPanel: React.FC<ResearchPanelProps> = ({ workspaceId, documents, pipelines, onOpenEvidence }) => {
  const tasks = useResearchTasks(workspaceId);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [composing, setComposing] = useState(false);
  const [warning, setWarning] = useState<ApiRequestError | null>(null);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div>
          <h2 className="font-serif text-base font-semibold">Research</h2>
          <p className="text-xs text-muted-foreground">Evidence-backed answers, comparisons, extraction and reports.</p>
        </div>
        {!composing && <button type="button" className={buttonPrimary} onClick={() => setComposing(true)}>New research</button>}
      </div>

      {composing && (
        <ResearchForm
          workspaceId={workspaceId}
          documents={documents}
          pipelines={pipelines}
          onCancel={() => setComposing(false)}
          onCreated={(task, queueWarning) => {
            setComposing(false);
            setWarning(queueWarning);
            setSelectedId(task.id);
            tasks.refresh();
          }}
        />
      )}
      {warning && (
        <div className="px-4 pt-3">
          <ErrorNotice title="Saved, but not started" code={warning.code} message={warning.message} />
        </div>
      )}
      {tasks.error && <div className="px-4 pt-3"><ErrorNotice code={tasks.error.code} message={tasks.error.message} /></div>}

      <section className="border-b border-border px-4 py-3" aria-label="Research tasks">
        <h3 className={eyebrow}>Tasks</h3>
        {tasks.loaded && tasks.list.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">No research yet. Verify a claim, compare documents or extract fields.</p>
        ) : (
          <ul className="mt-2 space-y-1">
            {tasks.list.map((task) => (
              <li key={task.id}>
                <button
                  type="button"
                  aria-current={selectedId === task.id ? "true" : undefined}
                  onClick={() => setSelectedId(task.id)}
                  className={`flex w-full items-baseline justify-between gap-2 px-2 py-1.5 text-left text-sm hover:bg-accent ${selectedId === task.id ? "bg-accent" : ""} ${focusRing}`}
                >
                  <span className="min-w-0 truncate" title={task.title}>{task.title}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">{task.kind_label} · {statusLabel(task.status)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {selectedId != null && (
        <ResearchResult
          key={selectedId}
          taskId={selectedId}
          onOpenEvidence={onOpenEvidence}
          onChanged={tasks.refresh}
          onDeleted={() => {
            setSelectedId(null);
            tasks.refresh();
          }}
        />
      )}
    </div>
  );
};

export default ResearchPanel;
