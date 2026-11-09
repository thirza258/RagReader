import React from "react";
import { deriveIngestionStages, statusLabel } from "../lib/ingestionStages";
import type { IngestionStageState, WorkspaceDocument } from "../types";

const GLYPH: Record<IngestionStageState, string> = { done: "✓", active: "●", pending: "○", failed: "✕" };
const STATE_TEXT: Record<IngestionStageState, string> = { done: "done", active: "in progress", pending: "not started", failed: "failed" };
const STATE_CLASS: Record<IngestionStageState, string> = {
  done: "text-foreground/80",
  active: "font-medium text-foreground",
  pending: "text-muted-foreground",
  failed: "font-medium text-destructive",
};
const GLYPH_CLASS: Record<IngestionStageState, string> = {
  done: "text-status-success",
  active: "text-primary motion-safe:animate-pulse",
  pending: "text-muted-foreground",
  failed: "text-destructive",
};

/**
 * The PRD §9 checklist: ✓ done, ● active, ○ pending, ✕ failed, with the
 * worker's own detail ("Embedded 640 of 1,000 chunks") under the active row.
 * Stage changes are announced politely; per-batch detail is not, so a long
 * embedding run does not chatter.
 */
const IngestionChecklist: React.FC<{ document: WorkspaceDocument; showProgress?: boolean }> = ({ document, showProgress = true }) => {
  const stages = deriveIngestionStages(document.status, document.error?.stage, { chunkCount: document.chunk_count });
  const active = stages.find((stage) => stage.state === "active");
  const progress = Math.max(0, Math.min(100, Math.round(document.progress || 0)));
  const announcement = `${document.title}: ${active ? active.text : statusLabel(document.status)}`;

  return (
    <div className="mt-2">
      <ol className="space-y-0.5 text-xs" aria-label={`Ingestion steps for ${document.title}`}>
        {stages.map((stage) => (
          <li key={stage.id} className={`flex gap-2 ${STATE_CLASS[stage.state]}`}>
            <span aria-hidden="true" className={`w-3 shrink-0 text-center ${GLYPH_CLASS[stage.state]}`}>
              {GLYPH[stage.state]}
            </span>
            <span className="min-w-0">
              {stage.text}
              <span className="sr-only"> ({STATE_TEXT[stage.state]})</span>
              {stage.state === "active" && document.status_detail && (
                <span className="block font-normal text-muted-foreground">{document.status_detail}</span>
              )}
            </span>
          </li>
        ))}
      </ol>
      {showProgress && document.status !== "FAILED" && (
        <div
          role="progressbar"
          aria-label={`Ingestion progress for ${document.title}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
          className="mt-2 h-[3px] w-full overflow-hidden bg-muted"
        >
          <div className="h-full bg-foreground/60 transition-[width] duration-700 ease-out" style={{ width: `${progress}%` }} />
        </div>
      )}
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
    </div>
  );
};

export default IngestionChecklist;
