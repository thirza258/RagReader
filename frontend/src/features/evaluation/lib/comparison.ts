import { formatCount, formatMs } from "../../runs/lib/runMetrics.ts";
import type { Comparison, ComparisonCell, ComparisonMetricRow, OperationalCell, OperationalRow } from "../types/index.ts";

/**
 * Reading an experiment comparison (PRD §30): signed deltas against the
 * baseline, whether a change is good or bad given the metric's direction,
 * bootstrap confidence intervals, wins and losses per question, and the
 * quality-versus-latency trade-off of each experiment.
 */

const DASH = "—";
const MINUS = "−";

export type Tone = "better" | "worse" | "same" | "unknown";

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** +0.10, −0.03, 0.00 (a zero has no sign); "—" when unknown. */
export function formatSigned(value: number | null | undefined, digits = 2): string {
  if (!isNumber(value)) return DASH;
  const rounded = Number(value.toFixed(digits));
  if (rounded === 0) return (0).toFixed(digits);
  const text = Math.abs(value).toFixed(digits);
  return value > 0 ? `+${text}` : `${MINUS}${text}`;
}

export const formatDelta = formatSigned;

/**
 * Whether a difference is an improvement. `epsilon` absorbs float noise; a
 * difference that rounds to zero at two decimals still counts as a change
 * here (the display decides how to show it).
 */
export function deltaTone(delta: number | null | undefined, higherIsBetter: boolean, epsilon = 1e-9): Tone {
  if (!isNumber(delta)) return "unknown";
  if (Math.abs(delta) <= epsilon) return "same";
  const improved = higherIsBetter ? delta > 0 : delta < 0;
  return improved ? "better" : "worse";
}

/** "[+0.02, +0.18]"; "" without an interval. */
export function formatCi(low: number | null | undefined, high: number | null | undefined, digits = 2): string {
  if (!isNumber(low) || !isNumber(high)) return "";
  return `[${formatSigned(low, digits)}, ${formatSigned(high, digits)}]`;
}

/** True when the interval lies entirely above or below zero. */
export function ciExcludesZero(low: number | null | undefined, high: number | null | undefined): boolean {
  return isNumber(low) && isNumber(high) && (low > 0 || high < 0);
}

/** "+0.10 [+0.02, +0.18]": the paired difference and its interval. */
export function ciText(cell: Pick<ComparisonCell, "paired_delta" | "delta" | "ci_low" | "ci_high">, digits = 2): string {
  const centre = isNumber(cell.paired_delta) ? cell.paired_delta : cell.delta;
  if (!isNumber(centre)) return DASH;
  const interval = formatCi(cell.ci_low, cell.ci_high, digits);
  return interval ? `${formatSigned(centre, digits)} ${interval}` : formatSigned(centre, digits);
}

export type Significance = "better" | "worse" | "inconclusive" | "unknown";

/**
 * From the confidence interval: an interval entirely on the good side of
 * zero is `better`, entirely on the bad side `worse`, one that contains zero
 * `inconclusive`; no interval (fewer than two pairs) is `unknown`.
 */
export function significance(cell: Pick<ComparisonCell, "ci_low" | "ci_high">, higherIsBetter: boolean): Significance {
  if (!isNumber(cell.ci_low) || !isNumber(cell.ci_high)) return "unknown";
  if (!ciExcludesZero(cell.ci_low, cell.ci_high)) return "inconclusive";
  const above = cell.ci_low > 0;
  return above === higherIsBetter ? "better" : "worse";
}

function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

/** "3 wins · 1 loss · 14 ties"; "—" on the baseline. */
export function winLossText(cell: Pick<ComparisonCell, "wins" | "losses" | "ties">): string {
  if (!isNumber(cell.wins) || !isNumber(cell.losses) || !isNumber(cell.ties)) return DASH;
  return [plural(cell.wins, "win"), plural(cell.losses, "loss", "losses"), plural(cell.ties, "tie")].join(" · ");
}

export function cellFor<T extends { experiment_id: number }>(cells: readonly T[] | null | undefined, experimentId: number): T | null {
  return cells?.find((cell) => cell.experiment_id === experimentId) ?? null;
}

export function metricRow(comparison: Pick<Comparison, "metrics"> | null | undefined, key: string): ComparisonMetricRow | null {
  return comparison?.metrics?.find((row) => row.key === key) ?? null;
}

export function operationalRow(comparison: Pick<Comparison, "operational"> | null | undefined, key: string): OperationalRow | null {
  return comparison?.operational?.find((row) => row.key === key) ?? null;
}

const OPERATIONAL_LABELS: Record<string, string> = {
  latency_p50_ms: "Latency p50",
  latency_p95_ms: "Latency p95",
  tokens_per_item: "Tokens per question",
  total_tokens: "Total tokens",
  cost_usd: "Cost (USD)",
};

export function operationalLabel(key: string): string {
  return OPERATIONAL_LABELS[key] ?? key.replace(/_/g, " ");
}

/** Latency in ms/s, tokens as counts, cost in dollars; "—" when unknown. */
export function formatOperational(key: string, value: number | null | undefined): string {
  if (!isNumber(value)) return DASH;
  if (key.endsWith("_ms")) return formatMs(value);
  if (key === "cost_usd") return `$${value.toFixed(value < 1 ? 4 : 2)}`;
  if (key === "tokens_per_item") return value.toLocaleString("en-US", { maximumFractionDigits: 1 });
  return formatCount(value);
}

/** "+120 ms", "−1,200", "+$0.0040"; "—" when unknown. */
export function formatOperationalDelta(key: string, delta: number | null | undefined): string {
  if (!isNumber(delta)) return DASH;
  if (delta === 0) return key.endsWith("_ms") ? "0 ms" : "0";
  const sign = delta > 0 ? "+" : MINUS;
  return `${sign}${formatOperational(key, Math.abs(delta))}`;
}

export function operationalTone(row: Pick<OperationalRow, "higher_is_better">, cell: Pick<OperationalCell, "delta">): Tone {
  return deltaTone(cell.delta, row.higher_is_better);
}

export type TradeOffKind =
  | "better_and_faster"
  | "better_but_slower"
  | "worse_but_faster"
  | "worse_and_slower"
  | "better_same_speed"
  | "worse_same_speed"
  | "same_quality_faster"
  | "same_quality_slower"
  | "no_clear_difference";

export interface TradeOff {
  kind: TradeOffKind;
  label: string;
  /** Quality and latency moved in opposite directions: a real trade-off. */
  tradeoff: boolean;
}

const TRADE_OFF_LABELS: Record<TradeOffKind, string> = {
  better_and_faster: "better and faster",
  better_but_slower: "better but slower",
  worse_but_faster: "worse but faster",
  worse_and_slower: "worse and slower",
  better_same_speed: "better, similar latency",
  worse_same_speed: "worse, similar latency",
  same_quality_faster: "similar quality, faster",
  same_quality_slower: "similar quality, slower",
  no_clear_difference: "no clear difference",
};

export interface TradeOffInput {
  /** Quality metric difference vs the baseline (higher is better). */
  qualityDelta: number | null | undefined;
  /** Its bootstrap interval, when there is one: it decides instead of the delta. */
  qualityCi?: { low: number | null | undefined; high: number | null | undefined } | null;
  latencyDeltaMs: number | null | undefined;
  baselineLatencyMs?: number | null;
  /** A quality change smaller than this is "similar" (without an interval). */
  qualityEpsilon?: number;
  /** A latency change smaller than max(this, 5% of the baseline) is "similar". */
  latencyEpsilonMs?: number;
}

/**
 * Quality versus latency for one experiment against the baseline. With a
 * confidence interval, quality counts as changed only when the interval
 * excludes zero; without one, when |delta| exceeds `qualityEpsilon`.
 */
export function tradeOff(input: TradeOffInput): TradeOff {
  const { qualityDelta, qualityCi, latencyDeltaMs, baselineLatencyMs } = input;
  const qualityEpsilon = input.qualityEpsilon ?? 0.005;
  let quality = 0;
  if (qualityCi && isNumber(qualityCi.low) && isNumber(qualityCi.high)) {
    if (qualityCi.low > 0) quality = 1;
    else if (qualityCi.high < 0) quality = -1;
  } else if (isNumber(qualityDelta) && Math.abs(qualityDelta) > qualityEpsilon) {
    quality = qualityDelta > 0 ? 1 : -1;
  }
  let latency = 0;
  if (isNumber(latencyDeltaMs)) {
    const threshold = Math.max(input.latencyEpsilonMs ?? 10, isNumber(baselineLatencyMs) ? Math.abs(baselineLatencyMs) * 0.05 : 0);
    if (Math.abs(latencyDeltaMs) > threshold) latency = latencyDeltaMs > 0 ? 1 : -1;
  }
  let kind: TradeOffKind;
  if (quality > 0) kind = latency < 0 ? "better_and_faster" : latency > 0 ? "better_but_slower" : "better_same_speed";
  else if (quality < 0) kind = latency < 0 ? "worse_but_faster" : latency > 0 ? "worse_and_slower" : "worse_same_speed";
  else kind = latency < 0 ? "same_quality_faster" : latency > 0 ? "same_quality_slower" : "no_clear_difference";
  return { kind, label: TRADE_OFF_LABELS[kind], tradeoff: kind === "better_but_slower" || kind === "worse_but_faster" };
}

export interface ExperimentTradeOff extends TradeOff {
  experimentId: number;
}

/** The trade-off of every non-baseline experiment for one quality metric. */
export function comparisonTradeOffs(comparison: Comparison | null | undefined, qualityKey: string): ExperimentTradeOff[] {
  if (!comparison) return [];
  const quality = metricRow(comparison, qualityKey);
  const latency = operationalRow(comparison, "latency_p50_ms");
  const baselineLatency = cellFor(latency?.cells, comparison.baseline_id)?.value ?? null;
  return comparison.experiments
    .filter((experiment) => experiment.id !== comparison.baseline_id)
    .map((experiment) => {
      const cell = cellFor(quality?.cells, experiment.id);
      const latencyCell = cellFor(latency?.cells, experiment.id);
      const result = tradeOff({
        qualityDelta: cell?.delta ?? null,
        qualityCi: cell && isNumber(cell.ci_low) && isNumber(cell.ci_high) ? { low: cell.ci_low, high: cell.ci_high } : null,
        latencyDeltaMs: latencyCell?.delta ?? null,
        baselineLatencyMs: baselineLatency,
      });
      return { experimentId: experiment.id, ...result };
    });
}

/** Config values for the differences table: strings as they are, the rest as JSON. */
export function configValueText(value: unknown): string {
  if (value === null || value === undefined) return DASH;
  if (typeof value === "string") return value || DASH;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/** "1,2,3" for the compare query; ids deduplicated, order kept. */
export function compareIdsParam(ids: readonly number[]): string {
  return [...new Set(ids.filter((id) => Number.isInteger(id) && id > 0))].join(",");
}
