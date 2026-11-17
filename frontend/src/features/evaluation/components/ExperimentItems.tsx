import React, { useState } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonOutline, buttonQuiet, eyebrow, focusRing, inputSmall } from "../../../components/ui/classes";
import type { Evidence } from "../../chat/types";
import RunTrace from "../../runs/components/RunTrace";
import { useRunDetail } from "../../runs/hooks/useRunDetail";
import { formatCount, formatMs } from "../../runs/lib/runMetrics";
import { useExperimentItems } from "../hooks/useExperiment";
import { describeSource } from "../lib/datasetCsv";
import { failureFilterOptions, failureFilterQuery, failureInfo, groupLabels } from "../lib/failures";
import { formatMetric, metricDefinition, metricLabel, sortMetricKeys } from "../lib/metrics";
import type { ExperimentItem, FailureCounts, ItemStatus, RetrievedEntry } from "../types";

const PAGE_SIZE = 50;

const RULE_LABELS: Record<string, string> = {
  chunk_id: "chunk id",
  char_overlap: "character range",
  page: "pages",
  document: "whole document",
  unresolved: "not found",
};

interface ExperimentItemsProps {
  experimentId: number;
  kValues: readonly number[];
  retrievalOnly: boolean;
  failures: FailureCounts | null;
  /** Changes as the run advances, so the table follows it. */
  progressKey: string;
  failureFilter: string;
  onFailureFilter: (value: string) => void;
  documentTitle: (documentId: number) => string | null;
  onOpenCandidate: (evidence: Evidence) => void;
}

function columnsFor(kValues: readonly number[], retrievalOnly: boolean): string[] {
  const sorted = [...kValues].sort((a, b) => a - b);
  const k = sorted.includes(5) ? 5 : (sorted.filter((value) => value <= 5).pop() ?? sorted[0]);
  const keys = k != null ? [`recall@${k}`, "mrr"] : ["mrr"];
  if (!retrievalOnly) keys.push("faithfulness", "answer_correctness");
  return keys;
}

function LabelChips({ item }: { item: ExperimentItem }) {
  if (item.failure_labels.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {item.failure_labels.map((label, index) => (
        <span
          key={`${label.code}-${index}`}
          title={label.detail || failureInfo(label.code).description}
          className={`border px-1 py-px text-[10px] ${label.category === "dataset" ? "border-status-warning/40 text-status-warning" : "border-destructive/40 text-destructive"}`}
        >
          {failureInfo(label.code).label}
        </span>
      ))}
    </span>
  );
}

function RetrievedList({ entries, titleFor }: { entries: readonly RetrievedEntry[]; titleFor: (id: number) => string | null }) {
  if (entries.length === 0) return <p className="text-muted-foreground">Nothing was retrieved.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-[11px] tabular">
        <thead className="text-muted-foreground">
          <tr className="border-b border-border">
            <th scope="col" className="py-0.5 pr-2 font-normal">#</th>
            <th scope="col" className="py-0.5 pr-2 font-normal">Document</th>
            <th scope="col" className="py-0.5 pr-2 font-normal">Chunk</th>
            <th scope="col" className="py-0.5 pr-2 font-normal">In context</th>
            <th scope="col" className="py-0.5 pr-2 font-normal">Cited</th>
            <th scope="col" className="py-0.5 pr-2 font-normal">Relevant</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={`${entry.rank}-${entry.chunk_id}`} className={`border-b border-border/60 ${entry.relevant ? "bg-status-success/5" : ""}`}>
              <td className="py-0.5 pr-2">{entry.rank}</td>
              <td className="max-w-[12rem] truncate py-0.5 pr-2">{entry.document_id != null ? (titleFor(entry.document_id) ?? `Document ${entry.document_id}`) : "—"}</td>
              <td className="py-0.5 pr-2 font-mono">{entry.chunk_id ?? "—"}</td>
              <td className="py-0.5 pr-2">{entry.in_context ? "yes" : "no"}</td>
              <td className="py-0.5 pr-2">{entry.cited == null ? "—" : entry.cited ? "yes" : "no"}</td>
              <td className="py-0.5 pr-2">{entry.relevant ? `yes (source ${entry.sources.map((source) => source + 1).join(", ")})` : "no"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1">
      <h5 className="text-xs font-medium">{title}</h5>
      {children}
    </section>
  );
}

function ItemDetail({ item, onClose, titleFor, onOpenCandidate }: { item: ExperimentItem; onClose: () => void; titleFor: (id: number) => string | null; onOpenCandidate: (evidence: Evidence) => void }) {
  const { run, error, loading, retry } = useRunDetail(item.run_id);
  const metricKeys = sortMetricKeys(Object.keys(item.metrics ?? {}));
  const groups = groupLabels(item.failure_labels);
  const latency = item.latency_ms;
  return (
    <section className="space-y-3 border border-border p-3 text-xs" aria-label={`Question ${item.item_id}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className={eyebrow}>
            {item.item_id} · {item.status}
          </p>
          <p className="mt-0.5 text-sm text-foreground">{item.question}</p>
        </div>
        <button type="button" className={buttonQuiet} onClick={onClose} aria-label="Close the question">
          <X aria-hidden="true" className="h-3.5 w-3.5" />
        </button>
      </div>
      {item.error && (
        <ErrorNotice title={`This question failed${item.error.stage ? ` during ${item.error.stage}` : ""}`} code={item.error.code} message={item.error.message} />
      )}
      {item.query && item.query.rewrite_applied && (
        <p>
          <span className="text-muted-foreground">Searched for:</span> “{item.query.used}” <span className="text-muted-foreground">(rewritten from the conversation)</span>
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Block title="Expected answer">
          <p className="whitespace-pre-wrap">{item.expected_answer || <span className="text-muted-foreground">None given</span>}</p>
        </Block>
        <Block title="Answer">
          <p className="whitespace-pre-wrap">{item.answer || <span className="text-muted-foreground">{item.answer == null ? "Not generated (retrieval only)" : "Empty"}</span>}</p>
        </Block>
      </div>
      <Block title="Expected sources and how they matched">
        {item.expected_sources.length === 0 ? (
          <p className="text-status-warning">No expected sources: retrieval cannot be judged for this question.</p>
        ) : (
          <ul className="space-y-0.5">
            {item.expected_sources.map((source, index) => {
              const match = item.matching.find((entry) => entry.source === index);
              return (
                <li key={index}>
                  <span className="font-mono text-muted-foreground">{index + 1}.</span> {describeSource(source, titleFor)}
                  {match && (
                    <span className={match.rule === "unresolved" ? "text-destructive" : "text-muted-foreground"}>
                      {" "}
                      — matched by {RULE_LABELS[match.rule] ?? match.rule}
                      {match.chunk_ids.length > 0 ? ` (${match.chunk_ids.length} ${match.chunk_ids.length === 1 ? "chunk" : "chunks"})` : ""}
                      {match.reason ? `: ${match.reason}` : ""}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Block>
      {groups.length > 0 && (
        <Block title="Failure analysis">
          {groups.map((group) => (
            <div key={group.category}>
              <p className="text-muted-foreground">{group.label}</p>
              <ul className="list-disc pl-4">
                {group.labels.map((label, index) => (
                  <li key={`${label.code}-${index}`}>
                    <span className="font-medium">{failureInfo(label.code).label}</span>
                    {label.detail ? ` — ${label.detail}` : ` — ${failureInfo(label.code).description}`}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </Block>
      )}
      <Block title="Metrics">
        <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-3 gap-y-0.5 tabular">
          {metricKeys.map((key) => (
            <React.Fragment key={key}>
              <dt className="text-muted-foreground" title={metricDefinition(key).definition}>
                {metricLabel(key)}
              </dt>
              <dd className="font-mono">{formatMetric(item.metrics[key], item.metric_reasons?.[key])}</dd>
            </React.Fragment>
          ))}
        </dl>
      </Block>
      <Block title="Retrieved passages">
        <RetrievedList entries={item.retrieved} titleFor={titleFor} />
      </Block>
      {item.alternative && (
        <Block title={`Retrieval with the other formulation: “${item.alternative.query}”`}>
          <RetrievedList entries={item.alternative.retrieved} titleFor={titleFor} />
        </Block>
      )}
      <p className="font-mono text-[11px] text-muted-foreground tabular">
        Latency {formatMs(latency?.total)} (retrieval {formatMs(latency?.retrieval)}, generation {formatMs(latency?.generation)}) · judge {formatMs(latency?.judge)} · tokens{" "}
        {formatCount(item.token_usage?.total_tokens)}
      </p>
      <Block title="Retrieval run">
        {item.run_id == null && <p className="text-muted-foreground">No run was recorded for this question.</p>}
        {loading && (
          <p role="status" className="text-muted-foreground">
            Loading the trace…
          </p>
        )}
        {error && (
          <ErrorNotice
            title="Could not load the run"
            code={error.code}
            message={error.message}
            actions={
              <button type="button" className={buttonOutline} onClick={retry}>
                Try again
              </button>
            }
          />
        )}
        {run && <RunTrace run={run} onOpenCandidate={onOpenCandidate} />}
      </Block>
    </section>
  );
}

/**
 * Every question of an experiment with its key metrics and failure labels
 * (PRD §31); filter by status or failure, open one to see how its sources
 * matched, what was retrieved, the answer, every metric with the reason a
 * value is missing, and its full retrieval run.
 */
const ExperimentItems: React.FC<ExperimentItemsProps> = ({
  experimentId,
  kValues,
  retrievalOnly,
  failures,
  progressKey,
  failureFilter,
  onFailureFilter,
  documentTitle,
  onOpenCandidate,
}) => {
  const [status, setStatus] = useState<ItemStatus | "">("");
  const [offset, setOffset] = useState(0);
  const [openPosition, setOpenPosition] = useState<number | null>(null);
  const query = { status: status || null, ...failureFilterQuery(failureFilter), offset, limit: PAGE_SIZE };
  const page = useExperimentItems(experimentId, query, progressKey);
  const columns = columnsFor(kValues, retrievalOnly);
  const open = page.items.find((item) => item.position === openPosition) ?? null;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={`items-status-${experimentId}`} className="text-[11px] text-muted-foreground">
          Status
        </label>
        <select
          id={`items-status-${experimentId}`}
          className={`${inputSmall} text-xs`}
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as ItemStatus | "");
            setOffset(0);
          }}
        >
          <option value="">All</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="pending">Pending</option>
        </select>
        <label htmlFor={`items-failure-${experimentId}`} className="text-[11px] text-muted-foreground">
          Failure
        </label>
        <select
          id={`items-failure-${experimentId}`}
          className={`${inputSmall} min-w-0 max-w-[16rem] text-xs`}
          value={failureFilter}
          onChange={(event) => {
            onFailureFilter(event.target.value);
            setOffset(0);
          }}
        >
          <option value="">Any (or none)</option>
          {failureFilterOptions(failures).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <span className="ml-auto text-[11px] text-muted-foreground tabular">
          {page.count} {page.count === 1 ? "question" : "questions"}
        </span>
      </div>

      {page.error && (
        <ErrorNotice
          title="Could not load the questions"
          code={page.error.code}
          message={page.error.message}
          actions={
            <button type="button" className={buttonOutline} onClick={page.refresh}>
              Try again
            </button>
          }
        />
      )}
      {!page.everLoaded && !page.error && (
        <p role="status" className="text-muted-foreground">
          Loading the questions…
        </p>
      )}

      {open && <ItemDetail key={open.position} item={open} onClose={() => setOpenPosition(null)} titleFor={documentTitle} onOpenCandidate={onOpenCandidate} />}

      {page.items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-[11px]">
            <caption className="sr-only">Questions of this experiment. Choose one to see its details and its retrieval run.</caption>
            <thead className="text-muted-foreground">
              <tr className="border-b border-border">
                <th scope="col" className="py-1 pr-2 font-normal">Id</th>
                <th scope="col" className="py-1 pr-2 font-normal">Question</th>
                {columns.map((key) => (
                  <th key={key} scope="col" className="py-1 pr-2 font-normal" title={metricDefinition(key).definition}>
                    {metricLabel(key)}
                  </th>
                ))}
                <th scope="col" className="py-1 pr-2 font-normal">Failures</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((item) => (
                <tr key={item.position} className={`border-b border-border/60 align-top ${item.position === openPosition ? "bg-accent" : ""}`}>
                  <td className="py-1 pr-2 font-mono">{item.item_id}</td>
                  <td className="min-w-[12rem] max-w-[20rem] py-1 pr-2">
                    <button type="button" className={`text-left hover:underline ${focusRing}`} onClick={() => setOpenPosition(item.position === openPosition ? null : item.position)}>
                      {item.question}
                    </button>
                    {item.status !== "completed" && <span className={`block ${item.status === "failed" ? "text-destructive" : "text-muted-foreground"}`}>{item.status}</span>}
                  </td>
                  {columns.map((key) => (
                    <td key={key} className="py-1 pr-2 font-mono tabular" title={item.metric_reasons?.[key] ? formatMetric(null, item.metric_reasons[key]) : undefined}>
                      {formatMetric(item.metrics?.[key] ?? null)}
                    </td>
                  ))}
                  <td className="py-1 pr-2">
                    <LabelChips item={item} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {page.everLoaded && page.items.length === 0 && !page.error && <p className="text-muted-foreground">No question matches these filters.</p>}

      {page.count > PAGE_SIZE && (
        <div className="flex items-center justify-end gap-1">
          <button type="button" className={buttonQuiet} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            <ChevronLeft aria-hidden="true" className="h-3.5 w-3.5" />
            Previous
          </button>
          <span className="text-[11px] text-muted-foreground tabular">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, page.count)} of {page.count}
          </span>
          <button type="button" className={buttonQuiet} disabled={offset + PAGE_SIZE >= page.count} onClick={() => setOffset(offset + PAGE_SIZE)}>
            Next
            <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
};

export default ExperimentItems;
