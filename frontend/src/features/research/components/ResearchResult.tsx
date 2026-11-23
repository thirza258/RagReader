import React, { useState } from "react";
import { Loader2 } from "lucide-react";
import { buttonOutline, buttonQuiet, buttonQuietDanger, eyebrow } from "../../../components/ui/classes";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import AnswerMarkdown from "../../chat/components/AnswerMarkdown";
import type { Evidence } from "../../chat/types";
import { cancelResearchTask, deleteResearchTask, exportResearchTask, retryResearchTask } from "../api/research";
import { useResearchTask } from "../hooks/useResearch";
import {
  evidenceFor, fieldStatusText, fieldValueText, isActive, orderedEvidence, statusLabel, verdictText, verdictTone,
} from "../lib/research";
import type {
  AskResult, ClaimResult, CompareResult, ContradictionsResult, ExtractResult, ReportResult, ResearchTask,
} from "../types";

interface ResearchResultProps {
  taskId: number;
  onOpenEvidence: (evidence: Evidence) => void;
  onChanged: () => void;
  onDeleted: () => void;
}

// The project's desaturated status tokens (tailwind.config.js). No `dark:`
// variants: the app has no dark theme, so they would fire on a light page
// whenever the OS prefers dark.
const TONES = {
  good: "border-status-success/40 bg-status-success/10 text-status-success",
  bad: "border-status-error/40 bg-status-error/10 text-status-error",
  mixed: "border-status-warning/40 bg-status-warning/10 text-status-warning",
  unknown: "border-border bg-muted text-muted-foreground",
};

function Text({ content, evidence, onOpen }: { content: string | null | undefined; evidence: readonly Evidence[]; onOpen: (e: Evidence) => void }) {
  if (!content) return <p className="text-sm text-muted-foreground">—</p>;
  return <AnswerMarkdown content={content} citations={evidence} onOpenSource={onOpen} />;
}

function Passage({ item, onOpen, note }: { item: Evidence; onOpen: (e: Evidence) => void; note?: string | null }) {
  return (
    <li className="border-l-2 border-border pl-3">
      <button type="button" className="text-left text-xs font-medium hover:underline" onClick={() => onOpen(item)}>
        [{item.citation_id}] {item.document_title}{item.page_number ? `, p. ${item.page_number}` : ""}
      </button>
      <p className="mt-0.5 line-clamp-3 text-sm text-foreground/85">{item.text}</p>
      {note && <p className="mt-0.5 text-xs text-muted-foreground">{note}</p>}
    </li>
  );
}

function ClaimView({ result, evidence, onOpen }: { result: ClaimResult; evidence: Evidence[]; onOpen: (e: Evidence) => void }) {
  const rationale = new Map(result.assessments.map((entry) => [entry.citation_id, entry.rationale] as const));
  const group = (title: string, ids: number[]) => (
    <section>
      <h4 className={eyebrow}>{title} ({ids.length})</h4>
      {ids.length === 0 ? <p className="mt-1 text-sm text-muted-foreground">None.</p> : (
        <ul className="mt-2 space-y-2">
          {evidenceFor(evidence, ids).map((item) => <Passage key={item.citation_id} item={item} onOpen={onOpen} note={rationale.get(item.citation_id)} />)}
        </ul>
      )}
    </section>
  );
  return (
    <div className="space-y-4">
      <p className="text-sm"><span className="font-medium">Claim:</span> {result.claim}</p>
      <p className={`inline-block border px-2 py-1 text-sm font-medium ${TONES[verdictTone(result.verdict)]}`}>
        {verdictText(result.verdict, result.confidence)}
      </p>
      <Text content={result.conclusion} evidence={evidence} onOpen={onOpen} />
      {group("Supporting evidence", result.supporting)}
      {group("Contradicting evidence", result.contradicting)}
      {result.counter_query && <p className="text-xs text-muted-foreground">Also searched for counter-evidence: “{result.counter_query}”.</p>}
    </div>
  );
}

function AskView({ result, evidence, onOpen }: { result: AskResult; evidence: Evidence[]; onOpen: (e: Evidence) => void }) {
  return (
    <div className="space-y-4">
      <p className="text-sm"><span className="font-medium">Question:</span> {result.question}</p>
      {result.per_document.map((row) => (
        <section key={row.document_id} className="border border-border p-3">
          <h4 className="text-sm font-medium">{row.document_title}</h4>
          {row.found ? <div className="mt-1"><Text content={row.answer} evidence={evidence} onOpen={onOpen} /></div>
            : <p className="mt-1 text-sm text-muted-foreground">Not addressed in this document's passages.</p>}
        </section>
      ))}
      <section><h4 className={eyebrow}>Comparison</h4><div className="mt-1"><Text content={result.comparison} evidence={evidence} onOpen={onOpen} /></div></section>
      <section><h4 className={eyebrow}>Synthesis</h4><div className="mt-1"><Text content={result.synthesis} evidence={evidence} onOpen={onOpen} /></div></section>
    </div>
  );
}

function CompareView({ result, evidence, onOpen }: { result: CompareResult; evidence: Evidence[]; onOpen: (e: Evidence) => void }) {
  return (
    <div className="space-y-4">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="py-2 pr-3 font-medium">Dimension</th>
              {result.documents.map((document) => <th key={document.id} scope="col" className="py-2 pr-3 font-medium">{document.title}</th>)}
              <th scope="col" className="py-2 font-medium">Difference</th>
            </tr>
          </thead>
          <tbody>
            {result.dimensions.map((row) => (
              <tr key={row.name} className="border-b border-border align-top">
                <th scope="row" className="py-2 pr-3 font-medium capitalize">{row.name}</th>
                {row.findings.map((cell) => (
                  <td key={cell.document_id} className="py-2 pr-3">
                    {cell.status === "found" ? <Text content={cell.finding} evidence={evidence} onOpen={onOpen} />
                      : <span className="text-muted-foreground">Not stated</span>}
                  </td>
                ))}
                <td className="py-2"><Text content={row.difference} evidence={evidence} onOpen={onOpen} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {result.summary && <Text content={result.summary} evidence={evidence} onOpen={onOpen} />}
    </div>
  );
}

function ExtractView({ result, evidence, onOpen }: { result: ExtractResult; evidence: Evidence[]; onOpen: (e: Evidence) => void }) {
  return (
    <div className="space-y-4">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="py-2 pr-3 font-medium">Field</th>
            <th scope="col" className="py-2 pr-3 font-medium">Value</th>
            <th scope="col" className="py-2 font-medium">Sources</th>
          </tr>
        </thead>
        <tbody>
          {result.fields.map((row) => (
            <tr key={row.name} className="border-b border-border align-top">
              <th scope="row" className="py-2 pr-3 font-mono text-xs font-medium">{row.name}</th>
              <td className="py-2 pr-3">{row.status === "found" ? fieldValueText(row.value) : <span className="text-muted-foreground">{fieldStatusText(row.status)}</span>}</td>
              <td className="py-2">
                {evidenceFor(evidence, row.citation_ids).map((item) => (
                  <button key={item.citation_id} type="button" className={buttonQuiet} onClick={() => onOpen(item)}>[{item.citation_id}]</button>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <details>
        <summary className="cursor-pointer text-xs text-muted-foreground">JSON</summary>
        <pre className="mt-2 overflow-x-auto bg-muted p-2 text-xs">{JSON.stringify(result.data, null, 2)}</pre>
      </details>
    </div>
  );
}

function ContradictionsView({ result, evidence, onOpen }: { result: ContradictionsResult; evidence: Evidence[]; onOpen: (e: Evidence) => void }) {
  return (
    <div className="space-y-4">
      <p className="text-sm"><span className="font-medium">Topic:</span> {result.topic}</p>
      {result.contradictions.length === 0 ? <p className="text-sm text-muted-foreground">No contradictions were found.</p> : (
        <ul className="space-y-3">
          {result.contradictions.map((pair) => (
            <li key={`${pair.a}-${pair.b}`} className="border border-border p-3">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {pair.severity === "direct" ? "Direct contradiction" : "Partial contradiction"}{pair.cross_document ? " · across documents" : ""}
              </p>
              {pair.explanation && <p className="mt-1 text-sm">{pair.explanation}</p>}
              <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                {evidenceFor(evidence, [pair.a, pair.b]).map((item) => <Passage key={item.citation_id} item={item} onOpen={onOpen} />)}
              </ul>
            </li>
          ))}
        </ul>
      )}
      {result.summary && <Text content={result.summary} evidence={evidence} onOpen={onOpen} />}
    </div>
  );
}

function ReportView({ result, evidence, onOpen }: { result: ReportResult; evidence: Evidence[]; onOpen: (e: Evidence) => void }) {
  return (
    <article className="space-y-4">
      <h4 className="font-serif text-lg font-semibold">{result.title}</h4>
      <section><h5 className={eyebrow}>Summary</h5><div className="mt-1"><Text content={result.summary} evidence={evidence} onOpen={onOpen} /></div></section>
      {result.sections.map((section) => (
        <section key={section.heading}><h5 className={eyebrow}>{section.heading}</h5><div className="mt-1"><Text content={section.body} evidence={evidence} onOpen={onOpen} /></div></section>
      ))}
      {result.limitations && <section><h5 className={eyebrow}>Limitations</h5><p className="mt-1 text-sm">{result.limitations}</p></section>}
    </article>
  );
}

function Body({ task, onOpen }: { task: ResearchTask; onOpen: (e: Evidence) => void }) {
  const evidence = task.evidence ?? [];
  const result = task.result;
  if (!result) return null;
  switch (task.kind) {
    case "verify_claim": return <ClaimView result={result as ClaimResult} evidence={evidence} onOpen={onOpen} />;
    case "ask": return <AskView result={result as AskResult} evidence={evidence} onOpen={onOpen} />;
    case "compare": return <CompareView result={result as CompareResult} evidence={evidence} onOpen={onOpen} />;
    case "extract": return <ExtractView result={result as ExtractResult} evidence={evidence} onOpen={onOpen} />;
    case "contradictions": return <ContradictionsView result={result as ContradictionsResult} evidence={evidence} onOpen={onOpen} />;
    case "report": return <ReportView result={result as ReportResult} evidence={evidence} onOpen={onOpen} />;
    default: return null;
  }
}

/** One research task: status, result, evidence, export (PRD §22–25, §47). */
const ResearchResult: React.FC<ResearchResultProps> = ({ taskId, onOpenEvidence, onChanged, onDeleted }) => {
  const { task, error, loading, refresh } = useResearchTask(taskId);
  const [actionError, setActionError] = useState<ApiRequestError | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setActionError(null);
    try {
      await action();
      refresh();
      onChanged();
    } catch (caught) {
      setActionError(toApiError(caught));
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <p className="p-4 text-sm text-muted-foreground" role="status">Loading the task…</p>;
  if (!task) return error ? <div className="p-4"><ErrorNotice title="The task could not be loaded" code={error.code} message={error.message} /></div> : null;
  const evidence = orderedEvidence(task.evidence);

  return (
    <section className="space-y-4 p-4" aria-labelledby={`research-task-${task.id}`}>
      <header>
        <p className={eyebrow}>{task.kind_label} · {statusLabel(task.status)}</p>
        <h3 id={`research-task-${task.id}`} className="mt-1 font-serif text-lg font-semibold">{task.title}</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          {task.documents.map((document) => document.title ?? `#${document.id}`).join(" · ")}
          {task.pipeline.name ? ` — ${task.pipeline.name} v${task.pipeline.version} (${task.pipeline.strategy})` : ""}
          {task.latency_ms != null ? ` — ${(task.latency_ms / 1000).toFixed(1)} s` : ""}
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {isActive(task.status) && <button type="button" className={buttonOutline} disabled={busy} onClick={() => act(() => cancelResearchTask(task.id))}>Cancel</button>}
          {(task.status === "failed" || task.status === "cancelled") && (
            <button type="button" className={buttonOutline} disabled={busy} onClick={() => act(() => retryResearchTask(task.id))}>Retry</button>
          )}
          {task.status === "completed" && (
            <button type="button" className={buttonOutline} disabled={busy} onClick={() => act(() => exportResearchTask(task.id, "md"))}>Export Markdown</button>
          )}
          {confirmDelete ? (
            <>
              <button type="button" className={buttonQuietDanger} disabled={busy} onClick={() => act(async () => { await deleteResearchTask(task.id); onDeleted(); })}>Delete for good</button>
              <button type="button" className={buttonQuiet} onClick={() => setConfirmDelete(false)}>Keep</button>
            </>
          ) : (
            <button type="button" className={buttonQuietDanger} onClick={() => setConfirmDelete(true)}>Delete</button>
          )}
        </div>
      </header>

      {isActive(task.status) && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status" aria-live="polite">
          <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
          {task.progress.detail || (task.status === "queued" ? "Waiting for a worker…" : "Working…")}
        </p>
      )}
      {task.error && (
        <ErrorNotice title="The task failed" code={task.error.code} message={task.error.message}>
          {task.error.stage && <p className="mt-1 text-xs">Stage: {task.error.stage}</p>}
        </ErrorNotice>
      )}
      {actionError && <ErrorNotice code={actionError.code} message={actionError.message} />}

      {task.status === "completed" && <Body task={task} onOpen={onOpenEvidence} />}

      {evidence.length > 0 && (
        <details className="border-t border-border pt-3">
          <summary className="cursor-pointer text-sm font-medium">Evidence ({evidence.filter((item) => item.cited).length} cited of {evidence.length})</summary>
          <ul className="mt-2 space-y-2">
            {evidence.map((item) => <Passage key={item.citation_id} item={item} onOpen={onOpenEvidence} note={item.cited ? "Cited" : "Retrieved, not cited"} />)}
          </ul>
        </details>
      )}
    </section>
  );
};

export default ResearchResult;
