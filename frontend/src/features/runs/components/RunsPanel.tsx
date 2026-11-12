import React, { useState } from "react";
import { ArrowLeft, Loader2, RefreshCw } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonOutline, buttonQuiet, eyebrow, focusRing, inputSmall } from "../../../components/ui/classes";
import type { Evidence } from "../../chat/types";
import { formatDateTime } from "../../documents/lib/format";
import { useRunDetail } from "../hooks/useRunDetail";
import { RUN_LIST_LIMIT, useRunsOverview } from "../hooks/useRunsOverview";
import { runLine, stageName, summaryCards } from "../lib/runMetrics";
import type { RetrievalRun } from "../types";
import RunTrace from "./RunTrace";

const WINDOWS = [7, 30, 90];

function RunRow({ run, onSelect }: { run: RetrievalRun; onSelect: (id: number) => void }) {
  const failed = run.status === "failed";
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(run.id)}
        className={`block w-full border-l-2 px-2.5 py-1.5 text-left transition-colors hover:bg-accent ${failed ? "border-destructive" : "border-border"} ${focusRing}`}
      >
        <span className="flex items-baseline justify-between gap-2 text-[11px] text-muted-foreground">
          <span>{formatDateTime(run.started_at)}</span>
          <span className={failed ? "font-medium text-destructive" : ""}>{failed ? "Failed" : "Completed"}</span>
        </span>
        <span className="mt-0.5 line-clamp-2 block text-sm text-foreground">{run.query?.original || "Untitled question"}</span>
        <span className="mt-0.5 block font-mono text-[11px] text-muted-foreground">{runLine(run)}</span>
        {failed && run.error && (
          <span className="mt-0.5 block text-[11px] text-destructive">
            Failed during {stageName(run.error.stage)} · <span className="font-mono">{run.error.code}</span>
          </span>
        )}
      </button>
    </li>
  );
}

function RunDetail({ runId, onBack, onOpenCandidate, onOpenConversation }: { runId: number; onBack: () => void; onOpenCandidate: (evidence: Evidence) => void; onOpenConversation: (id: number) => void }) {
  const { run, error, loading, retry } = useRunDetail(runId);
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 custom-scrollbar">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <button type="button" className={buttonQuiet} onClick={onBack}>
          <ArrowLeft aria-hidden="true" className="h-3.5 w-3.5" />
          All runs
        </button>
        {run?.conversation_id != null && (
          <button type="button" className={buttonQuiet} onClick={() => onOpenConversation(run.conversation_id!)}>
            Open the conversation
          </button>
        )}
      </div>
      <h3 className="text-sm font-medium">Run #{runId}</h3>
      {loading && (
        <p role="status" className="mt-2 text-xs text-muted-foreground">
          Loading the trace…
        </p>
      )}
      {error && (
        <ErrorNotice
          className="mt-2"
          title="Could not load this run"
          code={error.code}
          message={error.message}
          actions={
            <button type="button" className={buttonOutline} onClick={retry}>
              Try again
            </button>
          }
        />
      )}
      {run && (
        <div className="mt-2">
          <RunTrace run={run} onOpenCandidate={onOpenCandidate} />
        </div>
      )}
    </div>
  );
}

interface RunsPanelProps {
  workspaceId: number;
  /** Changes after every chat turn, so the list stays current. */
  version: number;
  selectedRunId: number | null;
  onSelectRun: (id: number | null) => void;
  onOpenCandidate: (evidence: Evidence) => void;
  onOpenConversation: (id: number) => void;
}

/**
 * The workspace's runs (PRD §32, §49): reliability over a window, then the
 * recent runs; choosing one opens its full trace.
 */
const RunsPanel: React.FC<RunsPanelProps> = ({ workspaceId, version, selectedRunId, onSelectRun, onOpenCandidate, onOpenConversation }) => {
  const [days, setDays] = useState(30);
  const [refresh, setRefresh] = useState(0);
  const overview = useRunsOverview(workspaceId, days, version + refresh);

  if (selectedRunId != null) {
    return <RunDetail runId={selectedRunId} onBack={() => onSelectRun(null)} onOpenCandidate={onOpenCandidate} onOpenConversation={onOpenConversation} />;
  }

  const cards = summaryCards(overview.summary);
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 custom-scrollbar">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">Reliability</h3>
        <div className="flex items-center gap-1.5">
          <label className="text-xs text-muted-foreground" htmlFor={`runs-window-${workspaceId}`}>
            Window
          </label>
          <select id={`runs-window-${workspaceId}`} className={`${inputSmall} text-xs`} value={days} onChange={(event) => setDays(Number(event.target.value))}>
            {WINDOWS.map((value) => (
              <option key={value} value={value}>
                Last {value} days
              </option>
            ))}
          </select>
          <button type="button" className={buttonQuiet} onClick={() => setRefresh((value) => value + 1)} aria-label="Refresh runs" disabled={!overview.loaded}>
            {overview.loaded ? <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" /> : <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />}
          </button>
        </div>
      </div>

      {overview.error && (
        <ErrorNotice
          className="mt-2"
          title="Could not load the runs"
          code={overview.error.code}
          message={overview.error.message}
          actions={
            <button type="button" className={buttonOutline} onClick={() => setRefresh((value) => value + 1)}>
              Try again
            </button>
          }
        />
      )}
      {!overview.everLoaded && !overview.error && (
        <p role="status" className="mt-2 text-xs text-muted-foreground">
          Loading runs…
        </p>
      )}

      {cards.length > 0 && (
        <dl className="mt-2 grid grid-cols-2 gap-px border border-border bg-border text-xs" aria-label={`Reliability over the last ${days} days`}>
          {cards.map((card) => (
            <div key={card.key} className="bg-background p-2">
              <dt className={eyebrow}>{card.label}</dt>
              <dd className="mt-0.5 font-mono text-sm text-foreground tabular">{card.value}</dd>
              <dd className="mt-0.5 text-[11px] text-muted-foreground">{card.detail}</dd>
            </div>
          ))}
        </dl>
      )}
      {overview.summary && overview.summary.ingestion.not_indexed > 0 && (
        <p className="mt-1 text-[11px] text-muted-foreground">
          {overview.summary.ingestion.not_indexed} older document{overview.summary.ingestion.not_indexed === 1 ? " was" : "s were"} never indexed and {overview.summary.ingestion.not_indexed === 1 ? "is" : "are"} not counted.
        </p>
      )}

      <h3 className="mt-4 text-sm font-medium">Recent runs</h3>
      {overview.everLoaded && overview.runs.length === 0 && !overview.error && (
        <p className="mt-1 text-xs text-muted-foreground">No runs yet. Every question asked in this workspace is recorded here with its trace.</p>
      )}
      {overview.runs.length > 0 && (
        <ul className="mt-1.5 space-y-1">
          {overview.runs.map((run) => (
            <RunRow key={run.id} run={run} onSelect={onSelectRun} />
          ))}
        </ul>
      )}
      {overview.hasMore && <p className="mt-2 text-[11px] text-muted-foreground">Showing the newest {RUN_LIST_LIMIT} runs.</p>}
    </div>
  );
};

export default RunsPanel;
