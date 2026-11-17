import type { MetricAggregate, MetricGroup } from "../types/index.ts";

/**
 * The evaluation metrics (PRD §27–28) as the server defines them
 * (docs/prd-implementation.md, Phase 4 "Metrics"): labels, groups, one-line
 * definitions, ordering, value formatting and the reasons a value is null.
 * Retrieval and generation metrics are separate groups everywhere.
 */

const DASH = "—";

interface BaseDefinition {
  label: string;
  group: MetricGroup;
  /** Computed at each K of the experiment (`recall@5`). */
  atK: boolean;
  definition: string;
}

const BASES: Record<string, BaseDefinition> = {
  recall: {
    label: "Recall",
    group: "retrieval",
    atK: true,
    definition: "Expected sources with at least one passage in the top K, as a share of the question's resolved expected sources.",
  },
  precision: {
    label: "Precision",
    group: "retrieval",
    atK: true,
    definition: "Distinct relevant passages in the top K divided by K, also when fewer than K passages were retrieved.",
  },
  hit_rate: {
    label: "Hit rate",
    group: "retrieval",
    atK: true,
    definition: "1 when the top K holds any relevant passage, else 0; the mean is the share of questions with a hit.",
  },
  ndcg: {
    label: "nDCG",
    group: "retrieval",
    atK: true,
    definition: "Rank-discounted gain over the top K, each expected source counted once, divided by the best possible ranking.",
  },
  mrr: {
    label: "MRR",
    group: "retrieval",
    atK: false,
    definition: "1 / rank of the first relevant passage among all candidates; 0 when none was retrieved.",
  },
  context_recall: {
    label: "Context recall",
    group: "retrieval",
    atK: false,
    definition: "Expected sources covered by the passages given to the model (top-k), as a share of the resolved expected sources.",
  },
  context_precision: {
    label: "Context precision",
    group: "retrieval",
    atK: false,
    definition: "Share of the passages given to the model that are relevant (PRD §28 context relevance).",
  },
  faithfulness: {
    label: "Faithfulness",
    group: "generation",
    atK: false,
    definition: "LLM judge: share of the answer's claims supported by the passages it was given.",
  },
  answer_relevance: {
    label: "Answer relevance",
    group: "generation",
    atK: false,
    definition: "LLM judge: how directly the answer addresses the question.",
  },
  answer_correctness: {
    label: "Answer correctness",
    group: "generation",
    atK: false,
    definition: "LLM judge: factual agreement (F1) of the answer with the expected answer.",
  },
  citation_correctness: {
    label: "Citation correctness",
    group: "generation",
    atK: false,
    definition: "Share of the cited passages that match an expected source.",
  },
  citation_completeness: {
    label: "Citation completeness",
    group: "generation",
    atK: false,
    definition: "Expected sources the answer cited, as a share of those present in the passages it was given.",
  },
};

/** Order of the metrics within their group. */
const RETRIEVAL_AT_K = ["recall", "precision", "hit_rate", "ndcg"];
const RETRIEVAL_OTHER = ["mrr", "context_recall", "context_precision"];
const GENERATION = ["faithfulness", "answer_relevance", "answer_correctness", "citation_correctness", "citation_completeness"];
export const GENERATION_METRICS: readonly string[] = GENERATION;

/** Why a metric has no value (stable server codes → people). */
const REASONS: Record<string, string> = {
  no_expected_sources: "no expected sources",
  expected_sources_unresolved: "expected sources not found in the index",
  empty_context: "no passages in the context",
  item_failed: "the item failed",
  retrieval_only: "not computed in a retrieval-only experiment",
  no_citations: "the answer cites nothing",
  no_expected_source_in_context: "no expected source reached the context",
  no_expected_answer: "no expected answer",
  no_answer: "the answer is empty",
  judge_unavailable: "the judge is not configured",
  judge_failed: "the judge gave no valid score",
  pricing_unavailable: "no pricing data for the models",
};

export interface MetricKey {
  base: string;
  k: number | null;
}

export interface MetricDefinition extends MetricKey {
  key: string;
  label: string;
  group: MetricGroup;
  definition: string;
  /** Every quality metric is better when higher. */
  higherIsBetter: boolean;
  known: boolean;
}

/** "recall@5" → {base: "recall", k: 5}; "mrr" → {base: "mrr", k: null}. */
export function parseMetricKey(key: string): MetricKey {
  const match = /^([a-z_]+)@(\d+)$/.exec(key ?? "");
  if (match) return { base: match[1], k: Number(match[2]) };
  return { base: key ?? "", k: null };
}

export function metricDefinition(key: string, fallbackGroup: MetricGroup = "retrieval"): MetricDefinition {
  const { base, k } = parseMetricKey(key);
  const known = BASES[base];
  if (!known || known.atK !== (k != null)) {
    return { key, base, k, label: key, group: fallbackGroup, definition: "", higherIsBetter: true, known: false };
  }
  const definition = k != null ? known.definition.replace(/\bK\b/g, String(k)) : known.definition;
  return {
    key,
    base,
    k,
    label: k != null ? `${known.label}@${k}` : known.label,
    group: known.group,
    definition,
    higherIsBetter: true,
    known: true,
  };
}

export function metricLabel(key: string): string {
  return metricDefinition(key).label;
}

export function metricGroup(key: string): MetricGroup {
  return metricDefinition(key).group;
}

function rank(key: string): [number, number, number, string] {
  const { base, k } = parseMetricKey(key);
  const atK = RETRIEVAL_AT_K.indexOf(base);
  if (atK >= 0 && k != null) return [0, atK, k, key];
  const other = RETRIEVAL_OTHER.indexOf(base);
  if (other >= 0 && k == null) return [1, other, 0, key];
  const generation = GENERATION.indexOf(base);
  if (generation >= 0 && k == null) return [2, generation, 0, key];
  return [3, 0, 0, key];
}

/**
 * Retrieval metrics first — Recall, Precision, Hit rate, nDCG (each by K
 * ascending), then MRR, context recall and precision — then generation
 * metrics in the contract's order; unknown keys last, alphabetically.
 */
export function sortMetricKeys(keys: Iterable<string>): string[] {
  return [...new Set(keys)].sort((a, b) => {
    const left = rank(a);
    const right = rank(b);
    for (let index = 0; index < 3; index += 1) {
      if (left[index] !== right[index]) return (left[index] as number) - (right[index] as number);
    }
    return left[3] < right[3] ? -1 : left[3] > right[3] ? 1 : 0;
  });
}

/** Every metric key an experiment with these K values reports, in display order. */
export function metricKeysFor(kValues: readonly number[], options: { retrievalOnly?: boolean } = {}): string[] {
  const keys: string[] = [];
  for (const base of RETRIEVAL_AT_K) for (const k of kValues) keys.push(`${base}@${k}`);
  keys.push(...RETRIEVAL_OTHER);
  if (!options.retrievalOnly) keys.push(...GENERATION);
  return sortMetricKeys(keys);
}

/** The human text for a null reason; unknown codes are shown as they are. */
export function reasonText(reason: string | null | undefined): string {
  if (!reason) return "";
  return REASONS[reason] ?? reason.replace(/_/g, " ");
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** 0.8234 → "0.82"; null → "—", or "— (no expected sources)" with a reason. */
export function formatMetric(value: number | null | undefined, reason?: string | null, digits = 2): string {
  if (isNumber(value)) return value.toFixed(digits);
  const why = reasonText(reason);
  return why ? `${DASH} (${why})` : DASH;
}

/** The most common null reason of an aggregate, or null. */
export function topReason(aggregate: MetricAggregate | null | undefined): string | null {
  if (!aggregate?.reasons) return null;
  let best: string | null = null;
  let most = 0;
  for (const [reason, count] of Object.entries(aggregate.reasons)) {
    if (count > most) {
      best = reason;
      most = count;
    }
  }
  return best;
}

export interface AggregateText {
  value: string;
  /** "16 questions", "16 of 18 questions · 2 without a value: no expected sources". */
  detail: string;
}

export function formatAggregate(aggregate: MetricAggregate | null | undefined, digits = 2): AggregateText {
  if (!aggregate) return { value: DASH, detail: "Not computed" };
  const count = aggregate.count ?? 0;
  const missing = aggregate.null_count ?? 0;
  const total = count + missing;
  const reason = topReason(aggregate);
  const value = isNumber(aggregate.mean) ? aggregate.mean.toFixed(digits) : DASH;
  if (total === 0) return { value, detail: "No completed questions yet" };
  const noun = total === 1 ? "question" : "questions";
  if (missing === 0) return { value, detail: `${count} ${noun}` };
  const why = reason ? `: ${reasonText(reason)}` : "";
  return { value, detail: `${count} of ${total} ${noun} · ${missing} without a value${why}` };
}

/** An item's value of one metric, with its null reason. */
export function itemMetricText(metrics: Record<string, number | null> | null | undefined, reasons: Record<string, string> | null | undefined, key: string): string {
  return formatMetric(metrics?.[key] ?? null, reasons?.[key] ?? null);
}
