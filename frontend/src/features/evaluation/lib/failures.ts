import type { FailureCategory, FailureCounts, FailureLabel } from "../types/index.ts";

/**
 * Failure analysis (PRD §31): what each label means, labels grouped by
 * category for an item, the experiment's counts in a fixed order (zeros
 * included, so the table never reshuffles), and the drill-down filter.
 */

export interface CategoryInfo {
  id: FailureCategory;
  label: string;
  description: string;
}

export const FAILURE_CATEGORIES: readonly CategoryInfo[] = [
  { id: "retrieval", label: "Retrieval failures", description: "The evidence did not reach the model." },
  { id: "generation", label: "Generation failures", description: "The model had the evidence but the answer falls short." },
  { id: "dataset", label: "Dataset problems", description: "The question or its expected evidence needs attention." },
];

export interface FailureCodeInfo {
  code: string;
  category: FailureCategory;
  label: string;
  description: string;
}

const CODES: readonly FailureCodeInfo[] = [
  {
    code: "relevant_not_retrieved",
    category: "retrieval",
    label: "Relevant passage not retrieved",
    description: "An expected source has no passage anywhere in the retrieved candidates.",
  },
  {
    code: "wrong_document",
    category: "retrieval",
    label: "Wrong document retrieved",
    description: "An expected source is missing from the context and most context passages come from other documents.",
  },
  {
    code: "insufficient_k",
    category: "retrieval",
    label: "Outside the top-k",
    description: "An expected source was retrieved, but ranked below the passages given to the model.",
  },
  {
    code: "query_mismatch",
    category: "retrieval",
    label: "Query mismatch",
    description: "The query used missed evidence that the other formulation (rewritten query or original question) retrieved.",
  },
  {
    code: "unsupported_claim",
    category: "generation",
    label: "Unsupported claim",
    description: "Faithfulness is below the threshold: the answer says things its passages do not support.",
  },
  {
    code: "citation_mismatch",
    category: "generation",
    label: "Citation mismatch",
    description: "The answer cites a passage that is not expected evidence, or cites none of the expected evidence it was given.",
  },
  {
    code: "incomplete_answer",
    category: "generation",
    label: "Incomplete answer",
    description: "Answer correctness against the expected answer is below the threshold.",
  },
  {
    code: "ambiguous_question",
    category: "dataset",
    label: "Ambiguous question",
    description: "The question has no expected source, so retrieval cannot be judged.",
  },
  {
    code: "missing_evidence",
    category: "dataset",
    label: "Missing evidence",
    description: "An expected source could not be found in the documents.",
  },
  {
    code: "duplicate_question",
    category: "dataset",
    label: "Duplicate question",
    description: "Another question in the dataset version asks the same thing.",
  },
];

const BY_CODE = new Map(CODES.map((info) => [info.code, info]));
const CATEGORY_ORDER: FailureCategory[] = ["retrieval", "generation", "dataset"];

export const FAILURE_CODES: readonly FailureCodeInfo[] = CODES;

function isCategory(value: unknown): value is FailureCategory {
  return value === "retrieval" || value === "generation" || value === "dataset";
}

export function failureInfo(code: string): FailureCodeInfo {
  return BY_CODE.get(code) ?? { code, category: "dataset", label: code.replace(/_/g, " "), description: "" };
}

export function failureLabel(code: string): string {
  return failureInfo(code).label;
}

export function categoryLabel(category: string): string {
  return FAILURE_CATEGORIES.find((item) => item.id === category)?.label ?? category;
}

export interface LabelGroup {
  category: FailureCategory;
  label: string;
  labels: FailureLabel[];
}

/** An item's labels by category, in the fixed category order; empty groups dropped. */
export function groupLabels(labels: readonly FailureLabel[] | null | undefined): LabelGroup[] {
  const groups = new Map<FailureCategory, FailureLabel[]>();
  for (const label of labels ?? []) {
    const category = isCategory(label.category) ? label.category : failureInfo(label.code).category;
    const list = groups.get(category) ?? [];
    list.push(label);
    groups.set(category, list);
  }
  return CATEGORY_ORDER.filter((category) => groups.has(category)).map((category) => ({
    category,
    label: categoryLabel(category),
    labels: groups.get(category) ?? [],
  }));
}

export interface CountRow {
  category: FailureCategory;
  label: string;
  total: number;
  codes: { code: string; label: string; description: string; count: number }[];
}

/** Every category and code with its count (0 when absent), in the fixed order. */
export function failureCountRows(failures: FailureCounts | null | undefined): CountRow[] {
  return CATEGORY_ORDER.map((category) => {
    const counts = (failures?.[category] ?? {}) as Record<string, number>;
    const codes = CODES.filter((info) => info.category === category).map((info) => ({
      code: info.code,
      label: info.label,
      description: info.description,
      count: Number.isFinite(counts[info.code]) ? counts[info.code] : 0,
    }));
    // Codes the server knows and this client does not are still shown.
    for (const [code, count] of Object.entries(counts)) {
      if (!BY_CODE.has(code)) codes.push({ code, label: failureLabel(code), description: "", count: Number.isFinite(count) ? count : 0 });
    }
    return { category, label: categoryLabel(category), total: codes.reduce((sum, row) => sum + row.count, 0), codes };
  });
}

export function totalLabelled(failures: FailureCounts | null | undefined): number {
  return failures?.items_with_failures ?? 0;
}

/** A drill-down filter: a whole category or one label (query `category=` or `label=`). */
export interface FailureFilter {
  value: string;
  label: string;
  query: { category?: FailureCategory; label?: string };
}

export function failureFilterOptions(failures?: FailureCounts | null): FailureFilter[] {
  const options: FailureFilter[] = [];
  for (const row of failureCountRows(failures)) {
    options.push({ value: `category:${row.category}`, label: failures ? `${row.label} (${row.total})` : row.label, query: { category: row.category } });
    for (const code of row.codes) {
      options.push({ value: `label:${code.code}`, label: `— ${code.label}${failures ? ` (${code.count})` : ""}`, query: { label: code.code } });
    }
  }
  return options;
}

/** The query of a filter value from `failureFilterOptions` ("" = no filter). */
export function failureFilterQuery(value: string): { category?: FailureCategory; label?: string } {
  if (value.startsWith("category:")) {
    const category = value.slice("category:".length);
    return isCategory(category) ? { category } : {};
  }
  if (value.startsWith("label:")) {
    const label = value.slice("label:".length);
    return label ? { label } : {};
  }
  return {};
}
