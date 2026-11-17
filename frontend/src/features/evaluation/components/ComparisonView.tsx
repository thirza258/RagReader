import React, { useState } from "react";
import { X } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonOutline, buttonQuiet, eyebrow, inputSmall } from "../../../components/ui/classes";
import { useComparison } from "../hooks/useComparison";
import {
  cellFor,
  ciExcludesZero,
  ciText,
  comparisonTradeOffs,
  configValueText,
  deltaTone,
  formatDelta,
  formatOperational,
  formatOperationalDelta,
  operationalLabel,
  significance,
  winLossText,
  type Tone,
} from "../lib/comparison";
import { MAX_COMPARE, datasetLabel, experimentLabel, pipelineLabel, warningTitle } from "../lib/experiments";
import { formatMetric, metricDefinition, metricLabel } from "../lib/metrics";
import type { Comparison, ComparisonMetricRow, Experiment } from "../types";

const TONE_CLASS: Record<Tone, string> = {
  better: "text-status-success",
  worse: "text-destructive",
  same: "text-muted-foreground",
  unknown: "text-muted-foreground",
};

interface ComparisonViewProps {
  /** Every experiment of the workspace, to name and add them. */
  experiments: readonly Experiment[];
  selectedIds: readonly number[];
  onRemove: (id: number) => void;
  onOpenExperiment: (id: number) => void;
  onPick: () => void;
}

function MetricRows({ rows, comparison, baselineId }: { rows: readonly ComparisonMetricRow[]; comparison: Comparison; baselineId: number }) {
  return (
    <>
      {rows.map((row) => {
        const definition = metricDefinition(row.key);
        return (
          <tr key={row.key} className="border-b border-border/60 align-top">
            <th scope="row" className="whitespace-nowrap py-1 pr-3 text-left font-medium" title={definition.definition}>
              {definition.label}
            </th>
            {comparison.experiments.map((experiment) => {
              const cell = cellFor(row.cells, experiment.id);
              if (!cell) return <td key={experiment.id} className="py-1 pr-3 text-muted-foreground">—</td>;
              const isBaseline = experiment.id === baselineId;
              const tone = deltaTone(cell.delta, row.higher_is_better);
              const verdict = significance(cell, row.higher_is_better);
              return (
                <td key={experiment.id} className="py-1 pr-3 tabular">
                  <span className="font-mono text-sm">{formatMetric(cell.mean)}</span>
                  <span className="ml-1 text-[10px] text-muted-foreground">n={cell.count}</span>
                  {!isBaseline && (
                    <span className="block font-mono text-[11px]">
                      <span className={TONE_CLASS[tone]}>Δ {formatDelta(cell.delta)}</span>
                      {(cell.ci_low != null || cell.paired_delta != null) && (
                        <span
                          className={`ml-1 ${verdict === "better" ? "text-status-success" : verdict === "worse" ? "text-destructive" : "text-muted-foreground"}`}
                          title={
                            ciExcludesZero(cell.ci_low, cell.ci_high)
                              ? "The 95% interval of the paired difference excludes zero."
                              : "The 95% interval of the paired difference includes zero: no clear difference."
                          }
                        >
                          {ciText(cell)}
                        </span>
                      )}
                    </span>
                  )}
                  {!isBaseline && cell.wins != null && <span className="block text-[10px] text-muted-foreground">{winLossText(cell)}</span>}
                </td>
              );
            })}
          </tr>
        );
      })}
    </>
  );
}

/**
 * Experiment comparison (PRD §30): every metric side by side with its
 * difference to the baseline, the paired bootstrap interval of that
 * difference and the per-question wins and losses; latency and tokens next
 * to quality so trade-offs are visible; what changed between the runs; and
 * the per-question outcomes for one metric.
 */
const ComparisonView: React.FC<ComparisonViewProps> = ({ experiments, selectedIds, onRemove, onOpenExperiment, onPick }) => {
  const [baseline, setBaseline] = useState<number | null>(null);
  const [metric, setMetric] = useState<string | null>(null);
  const effectiveBaseline = baseline != null && selectedIds.includes(baseline) ? baseline : (selectedIds[0] ?? null);
  const { comparison, error, loading, refresh } = useComparison(selectedIds, effectiveBaseline, metric);
  const nameOf = (id: number) => {
    const experiment = experiments.find((item) => item.id === id) ?? comparison?.experiments.find((item) => item.id === id);
    return experiment ? experimentLabel(experiment) : `#${id}`;
  };

  const header = (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">Compare experiments</h3>
        <button type="button" className={buttonQuiet} onClick={onPick}>
          Choose in the registry
        </button>
      </div>
      {selectedIds.length < 2 ? (
        <p className="text-muted-foreground">
          Tick 2–{MAX_COMPARE} experiments on the same dataset in the Experiments registry, then come back here.
        </p>
      ) : (
        <ul className="flex flex-wrap gap-1" aria-label="Experiments compared">
          {selectedIds.map((id) => (
            <li key={id} className="inline-flex items-center gap-1 border border-border px-1.5 py-0.5">
              <button type="button" className="hover:underline" onClick={() => onOpenExperiment(id)}>
                {nameOf(id)}
              </button>
              {id === effectiveBaseline && <span className="text-[10px] text-muted-foreground">(baseline)</span>}
              <button type="button" className={buttonQuiet} onClick={() => onRemove(id)} aria-label={`Remove ${nameOf(id)} from the comparison`}>
                <X aria-hidden="true" className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  if (selectedIds.length < 2) return <div className="space-y-3 text-xs">{header}</div>;

  const retrievalRows = comparison?.metrics.filter((row) => row.group === "retrieval") ?? [];
  const generationRows = comparison?.metrics.filter((row) => row.group !== "retrieval") ?? [];
  const qualityKey = comparison?.items?.metric ?? metric ?? "mrr";
  const tradeOffs = comparisonTradeOffs(comparison, qualityKey);
  const baselineId = comparison?.baseline_id ?? effectiveBaseline ?? 0;

  return (
    <div className="space-y-4 text-xs">
      {header}
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="compare-baseline" className="text-[11px] text-muted-foreground">
          Baseline
        </label>
        <select id="compare-baseline" className={`${inputSmall} text-xs`} value={effectiveBaseline ?? ""} onChange={(event) => setBaseline(Number(event.target.value))}>
          {selectedIds.map((id) => (
            <option key={id} value={id}>
              {nameOf(id)}
            </option>
          ))}
        </select>
        {comparison && (
          <>
            <label htmlFor="compare-metric" className="text-[11px] text-muted-foreground">
              Per-question metric
            </label>
            <select id="compare-metric" className={`${inputSmall} text-xs`} value={qualityKey} onChange={(event) => setMetric(event.target.value)}>
              {comparison.metrics.map((row) => (
                <option key={row.key} value={row.key}>
                  {metricLabel(row.key)}
                </option>
              ))}
            </select>
          </>
        )}
        {loading && (
          <span role="status" className="text-[11px] text-muted-foreground">
            Comparing…
          </span>
        )}
      </div>

      {error && (
        <ErrorNotice
          title="Could not compare these experiments"
          code={error.code}
          message={error.message}
          actions={
            <button type="button" className={buttonOutline} onClick={refresh}>
              Try again
            </button>
          }
        />
      )}

      {comparison && (
        <>
          {comparison.warnings.length > 0 && (
            <section className="space-y-1" aria-label="Warnings">
              {comparison.warnings.map((warning, index) => (
                <p key={`${warning.code}-${index}`} className="border-l-2 border-status-warning pl-2">
                  <span className="font-medium">{warningTitle(warning.code)}</span> — {warning.message}
                  {warning.experiment_ids?.length ? <span className="text-muted-foreground"> ({warning.experiment_ids.map((id) => `#${id}`).join(", ")})</span> : null}
                </p>
              ))}
            </section>
          )}

          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-[11px]">
              <caption className="pb-1 text-left text-muted-foreground">
                Mean per experiment; under each, the difference to the baseline (Δ), the paired difference with its {Math.round((comparison.bootstrap?.confidence ?? 0.95) * 100)}% bootstrap
                interval ({(comparison.bootstrap?.resamples ?? 0).toLocaleString("en-US")} resamples, seed {comparison.bootstrap?.seed}) and the per-question wins, losses and ties.
              </caption>
              <thead>
                <tr className="border-b border-border align-bottom">
                  <th scope="col" className="py-1 pr-3 font-normal text-muted-foreground">
                    Metric
                  </th>
                  {comparison.experiments.map((experiment) => (
                    <th key={experiment.id} scope="col" className="min-w-[9rem] py-1 pr-3 font-normal">
                      <button type="button" className="text-left font-medium hover:underline" onClick={() => onOpenExperiment(experiment.id)}>
                        {experimentLabel(experiment)}
                      </button>
                      <span className="block text-muted-foreground">
                        {pipelineLabel(experiment.pipeline)}
                        {experiment.pipeline?.strategy ? ` · ${experiment.pipeline.strategy}` : ""}
                      </span>
                      <span className="block text-muted-foreground">
                        {datasetLabel(experiment.dataset)} · {experiment.retrieval_only ? "retrieval only" : "full"}
                      </span>
                      {experiment.id === comparison.baseline_id && <span className={eyebrow}>Baseline</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th colSpan={comparison.experiments.length + 1} scope="rowgroup" className={`pt-2 text-left ${eyebrow}`}>
                    Retrieval quality
                  </th>
                </tr>
                <MetricRows rows={retrievalRows} comparison={comparison} baselineId={baselineId} />
                {generationRows.length > 0 && (
                  <tr>
                    <th colSpan={comparison.experiments.length + 1} scope="rowgroup" className={`pt-2 text-left ${eyebrow}`}>
                      Generation quality
                    </th>
                  </tr>
                )}
                <MetricRows rows={generationRows} comparison={comparison} baselineId={baselineId} />
                <tr>
                  <th colSpan={comparison.experiments.length + 1} scope="rowgroup" className={`pt-2 text-left ${eyebrow}`}>
                    Latency and cost (lower is better)
                  </th>
                </tr>
                {comparison.operational.map((row) => (
                  <tr key={row.key} className="border-b border-border/60 align-top">
                    <th scope="row" className="whitespace-nowrap py-1 pr-3 text-left font-medium">
                      {operationalLabel(row.key)}
                    </th>
                    {comparison.experiments.map((experiment) => {
                      const cell = cellFor(row.cells, experiment.id);
                      const tone = deltaTone(cell?.delta, row.higher_is_better);
                      return (
                        <td key={experiment.id} className="py-1 pr-3 font-mono tabular">
                          {formatOperational(row.key, cell?.value)}
                          {experiment.id !== comparison.baseline_id && cell?.delta != null && <span className={`block text-[11px] ${TONE_CLASS[tone]}`}>Δ {formatOperationalDelta(row.key, cell.delta)}</span>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {tradeOffs.length > 0 && (
            <section className="space-y-1">
              <h4 className="text-xs font-medium">Trade-offs on {metricLabel(qualityKey)} vs latency p50</h4>
              <ul className="space-y-0.5">
                {tradeOffs.map((entry) => (
                  <li key={entry.experimentId} className={entry.tradeoff ? "border-l-2 border-status-warning pl-2" : "pl-2.5"}>
                    {nameOf(entry.experimentId)}: <span className={entry.tradeoff ? "font-medium text-status-warning" : ""}>{entry.label}</span> than the baseline
                  </li>
                ))}
              </ul>
              <p className="text-[11px] text-muted-foreground">Quality counts as changed only when its interval excludes zero (or, without one, beyond ±0.005); latency beyond 5% or 10 ms.</p>
            </section>
          )}

          {comparison.config_differences.length > 0 && (
            <section className="space-y-1">
              <h4 className="text-xs font-medium">What differs between them</h4>
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-left text-[11px]">
                  <thead className="text-muted-foreground">
                    <tr className="border-b border-border">
                      <th scope="col" className="py-0.5 pr-3 font-normal">
                        Setting
                      </th>
                      {comparison.experiments.map((experiment) => (
                        <th key={experiment.id} scope="col" className="py-0.5 pr-3 font-normal">
                          #{experiment.id}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.config_differences.map((difference) => (
                      <tr key={difference.key} className="border-b border-border/60">
                        <th scope="row" className="py-0.5 pr-3 text-left font-mono font-normal">
                          {difference.key}
                        </th>
                        {comparison.experiments.map((experiment, index) => (
                          <td key={experiment.id} className="max-w-[14rem] break-all py-0.5 pr-3 font-mono">
                            {configValueText(difference.values[index])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section className="space-y-1">
            <h4 className="text-xs font-medium">Per question: {metricLabel(comparison.items.metric)}</h4>
            {comparison.items.rows.length === 0 ? (
              <p className="text-muted-foreground">No question is shared by these experiments.</p>
            ) : (
              <div className="max-h-[28rem] overflow-auto">
                <table className="w-full border-collapse text-left text-[11px]">
                  <caption className="sr-only">Per-question values of {metricLabel(comparison.items.metric)}, with wins and losses against the baseline</caption>
                  <thead className="sticky top-0 bg-background text-muted-foreground">
                    <tr className="border-b border-border">
                      <th scope="col" className="py-0.5 pr-2 font-normal">
                        Id
                      </th>
                      <th scope="col" className="py-0.5 pr-2 font-normal">
                        Question
                      </th>
                      {comparison.experiments.map((experiment) => (
                        <th key={experiment.id} scope="col" className="py-0.5 pr-2 font-normal">
                          #{experiment.id}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.items.rows.map((row) => (
                      <tr key={row.item_id} className="border-b border-border/60 align-top">
                        <td className="py-0.5 pr-2 font-mono">{row.item_id}</td>
                        <td className="min-w-[10rem] max-w-[18rem] py-0.5 pr-2">{row.question}</td>
                        {comparison.experiments.map((experiment) => {
                          const cell = cellFor(row.cells, experiment.id);
                          const outcome = cell?.outcome ?? null;
                          return (
                            <td key={experiment.id} className="py-0.5 pr-2 font-mono tabular">
                              {formatMetric(cell?.value ?? null)}
                              {outcome && (
                                <span className={`ml-1 ${outcome === "win" ? "text-status-success" : outcome === "loss" ? "text-destructive" : "text-muted-foreground"}`}>
                                  {outcome === "win" ? "▲ win" : outcome === "loss" ? "▼ loss" : "= tie"}
                                </span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
};

export default ComparisonView;
