import React, { useState } from "react";
import { ArrowLeft, Ban, Play, RotateCcw, Trash2 } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonDanger, buttonOutline, buttonPrimary, buttonQuiet, buttonQuietDanger, eyebrow, inputBase } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import type { Evidence } from "../../chat/types";
import { formatDateTime } from "../../documents/lib/format";
import { formatCount, formatMs } from "../../runs/lib/runMetrics";
import { cancelExperiment, deleteExperiment, rerunExperiment, startExperiment, updateExperiment, type StartResult } from "../api/evaluation";
import { useExperiment } from "../hooks/useExperiment";
import { failureCountRows } from "../lib/failures";
import { datasetLabel, experimentActions, isActive, pipelineLabel, runtimeText, warningTitle } from "../lib/experiments";
import { formatAggregate, metricDefinition, reasonText, sortMetricKeys } from "../lib/metrics";
import type { Aggregates, ExperimentDetail as ExperimentDetailData, ExperimentWarning, MetricAggregate } from "../types";
import ApiErrorNotice from "./ApiErrorNotice";
import ExperimentItems from "./ExperimentItems";
import ProgressBar from "./ProgressBar";
import StatusBadge from "./StatusBadge";

interface ExperimentDetailProps {
  experimentId: number;
  onBack: () => void;
  /** After a start, cancel, rerun or delete, so the registry stays current. */
  onChanged: () => void;
  onDeleted: (id: number) => void;
  onOpenExperiment: (id: number) => void;
  documentTitle: (documentId: number) => string | null;
  onOpenCandidate: (evidence: Evidence) => void;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8.5rem_1fr] gap-2 py-1">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function MetricGroupTable({ title, metrics, emptyText }: { title: string; metrics: Record<string, MetricAggregate> | undefined; emptyText: string }) {
  const keys = sortMetricKeys(Object.keys(metrics ?? {}));
  return (
    <section className="space-y-1">
      <h4 className="text-xs font-medium">{title}</h4>
      {keys.length === 0 ? (
        <p className="text-muted-foreground">{emptyText}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-[11px]">
            <caption className="sr-only">{title}: mean over the questions with a value</caption>
            <thead className="text-muted-foreground">
              <tr className="border-b border-border">
                <th scope="col" className="py-1 pr-2 font-normal">Metric</th>
                <th scope="col" className="py-1 pr-2 font-normal">Mean</th>
                <th scope="col" className="py-1 pr-2 font-normal">Over</th>
                <th scope="col" className="py-1 font-normal">Definition</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((key) => {
                const definition = metricDefinition(key);
                const text = formatAggregate(metrics?.[key]);
                return (
                  <tr key={key} className="border-b border-border/60 align-top">
                    <th scope="row" className="whitespace-nowrap py-1 pr-2 font-medium">
                      {definition.label}
                    </th>
                    <td className="py-1 pr-2 font-mono text-sm tabular">{text.value}</td>
                    <td className="py-1 pr-2 text-muted-foreground">{text.detail}</td>
                    <td className="min-w-[14rem] py-1 text-muted-foreground">{definition.definition}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Operational({ metrics }: { metrics: Aggregates }) {
  const latency = metrics.latency_ms ?? {};
  const rows: [string, keyof typeof latency][] = [
    ["Total (rewrite + retrieval + generation)", "total"],
    ["Retrieval", "retrieval"],
    ["Generation", "generation"],
    ["Judge (not part of the total)", "judge"],
  ];
  const tokens = metrics.tokens;
  return (
    <section className="grid gap-3 sm:grid-cols-2">
      <div className="space-y-1">
        <h4 className="text-xs font-medium">Latency per question</h4>
        <dl className="tabular">
          {rows.map(([label, key]) => {
            const stat = latency[key];
            return (
              <div key={key} className="flex justify-between gap-2">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="font-mono">{stat && stat.count > 0 ? `p50 ${formatMs(stat.p50)} · p95 ${formatMs(stat.p95)}` : "—"}</dd>
              </div>
            );
          })}
        </dl>
      </div>
      <div className="space-y-1">
        <h4 className="text-xs font-medium">Tokens and cost</h4>
        <dl className="tabular">
          <div className="flex justify-between gap-2">
            <dt className="text-muted-foreground">Generation tokens</dt>
            <dd className="font-mono">
              {formatCount(tokens?.total)} ({formatCount(tokens?.prompt)} prompt · {formatCount(tokens?.completion)} completion)
            </dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-muted-foreground">Per question</dt>
            <dd className="font-mono">{tokens?.per_item != null ? tokens.per_item.toLocaleString("en-US", { maximumFractionDigits: 1 }) : "—"}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-muted-foreground">Cost</dt>
            <dd className="font-mono">{metrics.cost?.usd != null ? `$${metrics.cost.usd.toFixed(4)}` : `— (${reasonText(metrics.cost?.reason) || "unknown"})`}</dd>
          </div>
        </dl>
        <p className="text-[11px] text-muted-foreground">The judge's tokens are not reported.</p>
      </div>
    </section>
  );
}

function WarningList({ warnings }: { warnings: readonly ExperimentWarning[] }) {
  if (warnings.length === 0) return null;
  return (
    <ul className="space-y-1">
      {warnings.map((warning, index) => (
        <li key={`${warning.code}-${index}`} className="border-l-2 border-status-warning pl-2">
          <span className="font-medium">{warningTitle(warning.code)}</span> — {warning.message}
        </li>
      ))}
    </ul>
  );
}

function ConclusionEditor({ experiment, onSaved }: { experiment: ExperimentDetailData; onSaved: () => void }) {
  const [value, setValue] = useState(experiment.conclusion ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiRequestError | null>(null);
  const [saved, setSaved] = useState(false);
  const changed = value.trim() !== (experiment.conclusion ?? "").trim();
  return (
    <section className="space-y-1">
      <label htmlFor={`conclusion-${experiment.id}`} className="text-xs font-medium">
        Conclusion
      </label>
      <textarea
        id={`conclusion-${experiment.id}`}
        rows={2}
        className={`${inputBase} text-sm`}
        value={value}
        placeholder="What did this experiment show? Was the hypothesis confirmed?"
        onChange={(event) => {
          setValue(event.target.value);
          setSaved(false);
        }}
      />
      {error && <ApiErrorNotice title="Could not save the conclusion" error={error} />}
      <div className="flex items-center gap-2">
        <button
          type="button"
          className={buttonOutline}
          disabled={busy || !changed}
          onClick={() =>
            void (async () => {
              setBusy(true);
              setError(null);
              try {
                await updateExperiment(experiment.id, { conclusion: value.trim() });
                setSaved(true);
                onSaved();
              } catch (caught) {
                setError(toApiError(caught));
              } finally {
                setBusy(false);
              }
            })()
          }
        >
          Save conclusion
        </button>
        {saved && !changed && (
          <span role="status" className="text-[11px] text-status-success">
            Saved.
          </span>
        )}
      </div>
    </section>
  );
}

function ConfigDetails({ experiment }: { experiment: ExperimentDetailData }) {
  const config = experiment.config;
  const pipelineConfig = config?.pipeline?.config ?? null;
  return (
    <details className="border border-border p-2">
      <summary className="cursor-pointer text-xs font-medium">Configuration, index versions and environment (§42)</summary>
      <div className="mt-2 space-y-3">
        {pipelineConfig && (
          <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px]">
            {Object.entries(pipelineConfig).map(([key, value]) => (
              <React.Fragment key={key}>
                <dt className="text-muted-foreground">{key}</dt>
                <dd className="break-all">{typeof value === "object" && value !== null ? JSON.stringify(value) : String(value)}</dd>
              </React.Fragment>
            ))}
            <dt className="text-muted-foreground">config_hash</dt>
            <dd className="break-all">{config.pipeline?.config_hash ?? "—"}</dd>
          </dl>
        )}
        <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px]">
          <dt className="text-muted-foreground">query_rewrite</dt>
          <dd>{String(config?.query_rewrite ?? "—")}</dd>
          <dt className="text-muted-foreground">thresholds</dt>
          <dd>{config?.thresholds ? `faithfulness ${config.thresholds.faithfulness} · answer_correctness ${config.thresholds.answer_correctness}` : "—"}</dd>
          <dt className="text-muted-foreground">dataset hash</dt>
          <dd className="break-all">{config?.dataset?.content_hash ?? experiment.dataset?.content_hash ?? "—"}</dd>
        </dl>
        {experiment.index_versions?.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-[11px]">
              <caption className="text-left text-xs font-medium">Index versions searched</caption>
              <thead className="text-muted-foreground">
                <tr className="border-b border-border">
                  <th scope="col" className="py-0.5 pr-2 font-normal">Document</th>
                  <th scope="col" className="py-0.5 pr-2 font-normal">Index</th>
                  <th scope="col" className="py-0.5 pr-2 font-normal">Method</th>
                  <th scope="col" className="py-0.5 pr-2 font-normal">Built</th>
                  <th scope="col" className="py-0.5 pr-2 font-normal">Embedding model</th>
                </tr>
              </thead>
              <tbody>
                {experiment.index_versions.map((entry) => (
                  <tr key={`${entry.document_id}-${entry.index_version_id}`} className="border-b border-border/60">
                    <td className="py-0.5 pr-2">{entry.document_title}</td>
                    <td className="py-0.5 pr-2 font-mono">{entry.index_version_id ?? "—"}</td>
                    <td className="py-0.5 pr-2">{entry.method ?? "—"}</td>
                    <td className="py-0.5 pr-2">{formatDateTime(entry.created_at)}</td>
                    <td className="py-0.5 pr-2 font-mono">{entry.embedding_model ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {experiment.environment && (
          <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px]">
            <dt className="text-muted-foreground">python</dt>
            <dd>{experiment.environment.python ?? "—"}</dd>
            {Object.entries(experiment.environment.packages ?? {}).map(([name, version]) => (
              <React.Fragment key={name}>
                <dt className="text-muted-foreground">{name}</dt>
                <dd>{version ?? "—"}</dd>
              </React.Fragment>
            ))}
            {Object.entries(experiment.environment.models ?? {}).map(([name, value]) => (
              <React.Fragment key={`model-${name}`}>
                <dt className="text-muted-foreground">model: {name}</dt>
                <dd className="break-all">{value == null ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value)}</dd>
              </React.Fragment>
            ))}
          </dl>
        )}
      </div>
    </details>
  );
}

/**
 * One experiment (PRD §29–31, §42): live progress, what it ran with, its
 * aggregate retrieval and generation metrics with their definitions,
 * latency and tokens, failure analysis with drill-down, reproducibility
 * warnings, and every question with its retrieval run.
 */
const ExperimentDetail: React.FC<ExperimentDetailProps> = ({ experimentId, onBack, onChanged, onDeleted, onOpenExperiment, documentTitle, onOpenCandidate }) => {
  const { experiment, error, loading, refresh } = useExperiment(experimentId);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<{ title: string; error: ApiRequestError } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [failureFilter, setFailureFilter] = useState("");

  const act = async (title: string, work: () => Promise<string | null>) => {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      const message = await work();
      if (message) setNotice(message);
      refresh();
      onChanged();
    } catch (caught) {
      setActionError({ title, error: toApiError(caught) });
    } finally {
      setBusy(false);
    }
  };
  const started = (result: StartResult, done: string) => (result.warning ? `${done} It could not be queued: ${result.warning.message}` : done);

  const back = (
    <button type="button" className={buttonQuiet} onClick={onBack}>
      <ArrowLeft aria-hidden="true" className="h-3.5 w-3.5" />
      All experiments
    </button>
  );
  if (!experiment) {
    return (
      <div className="space-y-2 text-xs">
        {back}
        {loading && (
          <p role="status" className="text-muted-foreground">
            Loading the experiment…
          </p>
        )}
        {error && (
          <ErrorNotice
            title={error.status === 404 ? "This experiment was not found" : "Could not load the experiment"}
            code={error.code}
            message={error.status === 404 ? "It may have been deleted." : error.message}
            actions={
              error.status !== 404 ? (
                <button type="button" className={buttonOutline} onClick={refresh}>
                  Try again
                </button>
              ) : undefined
            }
          />
        )}
      </div>
    );
  }

  const actions = experimentActions(experiment.status);
  const metrics = experiment.metrics;
  const failureRows = failureCountRows(experiment.failures);
  const progressKey = `${experiment.status}:${experiment.progress?.completed ?? 0}:${experiment.progress?.failed ?? 0}`;
  const warnings = [...(experiment.warnings ?? []), ...(experiment.reproducibility?.warnings ?? [])].filter(
    (warning, index, all) => all.findIndex((other) => other.code === warning.code && other.message === warning.message) === index,
  );

  return (
    <div className="space-y-4 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {back}
        <div className="flex flex-wrap items-center gap-1">
          {actions.start && (
            <button type="button" className={buttonPrimary} disabled={busy} onClick={() => void act("Could not start the experiment", async () => started(await startExperiment(experiment.id), "Started."))}>
              <Play aria-hidden="true" className="h-3.5 w-3.5" />
              Start
            </button>
          )}
          {actions.resume && (
            <button
              type="button"
              className={buttonPrimary}
              disabled={busy}
              onClick={() => void act("Could not resume the experiment", async () => started(await startExperiment(experiment.id), "Resumed: completed questions are kept, the rest run now."))}
            >
              <Play aria-hidden="true" className="h-3.5 w-3.5" />
              Resume
            </button>
          )}
          {actions.cancel && (
            <button
              type="button"
              className={buttonOutline}
              disabled={busy}
              onClick={() =>
                void act("Could not cancel the experiment", async () => {
                  await cancelExperiment(experiment.id);
                  return "Cancelled. Resume continues from the completed questions.";
                })
              }
            >
              <Ban aria-hidden="true" className="h-3.5 w-3.5" />
              Cancel
            </button>
          )}
          {actions.rerun && (
            <button
              type="button"
              className={buttonOutline}
              disabled={busy}
              onClick={() =>
                void act("Could not rerun the experiment", async () => {
                  const result = await rerunExperiment(experiment.id);
                  onOpenExperiment(result.experiment.id);
                  return null;
                })
              }
            >
              <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" />
              Rerun
            </button>
          )}
          <button type="button" className={buttonQuietDanger} disabled={busy} onClick={() => setConfirmDelete(true)} aria-label="Delete the experiment">
            <Trash2 aria-hidden="true" className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <header className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-medium">
            <span className="font-mono text-muted-foreground">#{experiment.id}</span> {experiment.name}
          </h3>
          <StatusBadge status={experiment.status} />
        </div>
        {experiment.hypothesis && (
          <p>
            <span className="text-muted-foreground">Hypothesis:</span> {experiment.hypothesis}
          </p>
        )}
        {(isActive(experiment.status) || experiment.status === "draft") && <ProgressBar progress={experiment.progress} />}
        {!isActive(experiment.status) && experiment.status !== "draft" && experiment.progress && (
          <p className="font-mono text-[11px] text-muted-foreground tabular">
            {experiment.progress.completed} completed · {experiment.progress.failed} failed · {experiment.progress.pending} pending
          </p>
        )}
      </header>

      {confirmDelete && (
        <div role="alertdialog" aria-labelledby={`experiment-delete-${experiment.id}`} className="space-y-2 border border-destructive/40 p-3">
          <p id={`experiment-delete-${experiment.id}`} className="font-medium">
            Delete this experiment and its {experiment.progress?.total ?? 0} evaluation runs?
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              className={buttonDanger}
              disabled={busy}
              onClick={() =>
                void (async () => {
                  setBusy(true);
                  try {
                    await deleteExperiment(experiment.id);
                    onDeleted(experiment.id);
                  } catch (caught) {
                    setActionError({ title: "Could not delete the experiment", error: toApiError(caught) });
                    setBusy(false);
                  }
                })()
              }
            >
              Delete
            </button>
            <button type="button" className={buttonOutline} onClick={() => setConfirmDelete(false)} disabled={busy}>
              Keep
            </button>
          </div>
        </div>
      )}

      {experiment.status === "failed" && experiment.error && (
        <ErrorNotice title="The experiment stopped" code={experiment.error.code} message={experiment.error.message}>
          {experiment.error.retryable && <p className="mt-1 text-[11px]">Resume continues from the completed questions.</p>}
        </ErrorNotice>
      )}
      {actionError && <ApiErrorNotice title={actionError.title} error={actionError.error} />}
      {notice && (
        <p role="status" className="border-l-2 border-status-success pl-2 text-foreground">
          {notice}
        </p>
      )}

      <dl className="divide-y divide-border border-y border-border">
        <Row label="Dataset">
          {datasetLabel(experiment.dataset)}
          {experiment.dataset && !experiment.dataset.available && <span className="text-muted-foreground"> (deleted since; questions are kept here)</span>}
        </Row>
        <Row label="Pipeline">
          {pipelineLabel(experiment.pipeline)}
          {experiment.pipeline?.strategy ? ` · ${experiment.pipeline.strategy}` : ""}
          {experiment.pipeline && !experiment.pipeline.available && <span className="text-muted-foreground"> (deleted since; its configuration is kept)</span>}
        </Row>
        <Row label="Measures">{experiment.retrieval_only ? "Retrieval only (no generation, no judge)" : "Retrieval and generation (LLM judge)"}</Row>
        <Row label="K values · seed">
          <span className="font-mono">
            {(experiment.k_values ?? []).join(", ")} · seed {experiment.seed}
          </span>
        </Row>
        {experiment.config?.judge_model && (
          <Row label="Judge model">
            <span className="font-mono">{experiment.config.judge_model}</span>
          </Row>
        )}
        <Row label="Documents">
          {experiment.index_versions?.length
            ? `${experiment.index_versions.length} ${experiment.index_versions.length === 1 ? "document" : "documents"}`
            : (experiment.config?.document_ids?.length ?? 0) > 0
              ? `${experiment.config.document_ids.length} documents`
              : "Resolved when the run starts"}
        </Row>
        <Row label="Runtime">{runtimeText(experiment.runtime_ms)}</Row>
        <Row label="Git commit">
          <span className="font-mono">{experiment.git_commit ?? "unknown"}</span>
        </Row>
        <Row label="Created">
          {formatDateTime(experiment.created_at)}
          {experiment.finished_at ? ` · finished ${formatDateTime(experiment.finished_at)}` : ""}
        </Row>
        {experiment.rerun_of != null && (
          <Row label="Rerun of">
            <button type="button" className="link" onClick={() => onOpenExperiment(experiment.rerun_of as number)}>
              Experiment #{experiment.rerun_of}
            </button>
          </Row>
        )}
      </dl>

      <ConclusionEditor key={experiment.id} experiment={experiment} onSaved={refresh} />

      {(warnings.length > 0 || experiment.reproducibility) && (
        <section className="space-y-1">
          <h4 className="text-xs font-medium">Reproducibility and hygiene</h4>
          {experiment.reproducibility && (
            <p className={experiment.reproducibility.status === "reproducible" ? "text-status-success" : "text-status-warning"}>
              {experiment.reproducibility.status === "reproducible"
                ? "The pipeline version, dataset version and index versions it used are unchanged: a rerun repeats it."
                : "Something it used has changed since; a rerun records the differences below."}
            </p>
          )}
          <WarningList warnings={warnings} />
        </section>
      )}

      {metrics ? (
        <>
          <MetricGroupTable title="Retrieval quality" metrics={metrics.retrieval} emptyText="No retrieval metrics yet." />
          <MetricGroupTable
            title="Generation quality"
            metrics={metrics.generation}
            emptyText={experiment.retrieval_only ? "Retrieval only: answers were not generated or judged." : "No generation metrics yet."}
          />
          <Operational metrics={metrics} />
        </>
      ) : (
        <p className="text-muted-foreground">Metrics appear as questions complete.</p>
      )}

      <section className="space-y-1">
        <h4 className="text-xs font-medium">Failure analysis</h4>
        <p className="text-muted-foreground">
          {experiment.failures?.items_with_failures ?? 0} {(experiment.failures?.items_with_failures ?? 0) === 1 ? "question has" : "questions have"} at least one label. Choose a
          label to list its questions.
        </p>
        <div className="grid gap-2 sm:grid-cols-3">
          {failureRows.map((row) => (
            <div key={row.category} className="border border-border p-2">
              <p className={eyebrow}>
                {row.label} · {row.total}
              </p>
              <ul className="mt-1 space-y-0.5">
                {row.codes.map((code) => (
                  <li key={code.code}>
                    <button
                      type="button"
                      className={`flex w-full justify-between gap-2 text-left hover:underline ${failureFilter === `label:${code.code}` ? "font-medium text-primary" : ""}`}
                      title={code.description}
                      onClick={() => setFailureFilter(failureFilter === `label:${code.code}` ? "" : `label:${code.code}`)}
                    >
                      <span>{code.label}</span>
                      <span className="font-mono tabular">{code.count}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-1">
        <h4 className="text-xs font-medium">Questions</h4>
        <ExperimentItems
          experimentId={experiment.id}
          kValues={experiment.k_values ?? []}
          retrievalOnly={experiment.retrieval_only}
          failures={experiment.failures}
          progressKey={progressKey}
          failureFilter={failureFilter}
          onFailureFilter={setFailureFilter}
          documentTitle={documentTitle}
          onOpenCandidate={onOpenCandidate}
        />
      </section>

      <ConfigDetails experiment={experiment} />
    </div>
  );
};

export default ExperimentDetail;
