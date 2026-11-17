/**
 * Research tasks: labels, verdict wording, and the form rules that mirror the
 * server's (research/services/runner.py). Plain TypeScript so tests can load it.
 */
import type { Evidence } from "../../chat/types";
import type { FieldSpec, FieldType, ResearchKind, ResearchStatus } from "../types";

export const POLL_MS = 2500;
export const FIELD_TYPES: readonly FieldType[] = ["text", "number", "list", "boolean"];
export const DEFAULT_DIMENSIONS: readonly string[] = [
  "methodology", "dataset", "retrieval", "reranking", "evaluation", "limitations", "conclusions",
];
export const LIMITS = { claim: 1000, question: 2000, topic: 500, title: 200, dimensions: 10, dimension: 80, fields: 20, compareMin: 2, compareMax: 4 };

export interface KindInfo {
  id: ResearchKind;
  label: string;
  description: string;
  /** The text input the kind asks for, if any. */
  prompt: "claim" | "question" | "topic" | null;
  placeholder: string;
}

export const KINDS: readonly KindInfo[] = [
  { id: "verify_claim", label: "Verify a claim", prompt: "claim",
    description: "Supporting and contradicting evidence, a verdict and a confidence.",
    placeholder: "Hybrid retrieval performs better than dense retrieval." },
  { id: "ask", label: "Ask across documents", prompt: "question",
    description: "An answer from each document, a comparison and a synthesis.",
    placeholder: "How do these papers differ in their retrieval methods?" },
  { id: "compare", label: "Compare documents", prompt: null,
    description: "Two to four documents side by side on chosen dimensions.", placeholder: "" },
  { id: "extract", label: "Extract fields", prompt: null,
    description: "Structured values, each with its source.", placeholder: "" },
  { id: "contradictions", label: "Find contradictions", prompt: "topic",
    description: "Passages that make incompatible statements.", placeholder: "Evaluation results" },
  { id: "report", label: "Write a report", prompt: "question",
    description: "A cited report with a summary, sections and limitations.",
    placeholder: "What do these documents conclude about reranking?" },
];

export function kindInfo(kind: string): KindInfo {
  return KINDS.find((entry) => entry.id === kind) ?? KINDS[0];
}

export function isActive(status: ResearchStatus | string | null | undefined): boolean {
  return status === "queued" || status === "running";
}

export function statusLabel(status: string): string {
  return ({ queued: "Queued", running: "Running", completed: "Completed", failed: "Failed", cancelled: "Cancelled" } as Record<string, string>)[status] ?? status;
}

export type Tone = "good" | "bad" | "mixed" | "unknown";

export function verdictText(verdict: string | null | undefined, confidence?: string | null): string {
  const label = ({ supported: "Supported", contradicted: "Contradicted", mixed: "Mixed evidence",
    insufficient_evidence: "Insufficient evidence" } as Record<string, string>)[verdict ?? ""] ?? "Unknown";
  return confidence && verdict !== "insufficient_evidence" ? `${label} · ${confidence} confidence` : label;
}

export function verdictTone(verdict: string | null | undefined): Tone {
  if (verdict === "supported") return "good";
  if (verdict === "contradicted") return "bad";
  if (verdict === "mixed") return "mixed";
  return "unknown";
}

/** Dimensions typed as "a, b" or one per line; trimmed, de-duplicated (case-insensitive). */
export function parseDimensions(text: string): string[] {
  const seen = new Set<string>();
  const dimensions: string[] = [];
  for (const part of text.split(/[,\n]/)) {
    const name = part.trim().replace(/\s+/g, " ");
    if (name && !seen.has(name.toLowerCase())) {
      seen.add(name.toLowerCase());
      dimensions.push(name);
    }
  }
  return dimensions;
}

const FIELD_NAME = /^[A-Za-z][A-Za-z0-9_]{0,59}$/;

/** Fields typed one per line as `name: type — description` (type and description optional). */
export function parseFieldSpecs(text: string): { fields: FieldSpec[]; errors: string[] } {
  const fields: FieldSpec[] = [];
  const errors: string[] = [];
  const names = new Set<string>();
  text.split("\n").forEach((line, index) => {
    const raw = line.trim();
    if (!raw) return;
    const [head, ...rest] = raw.split(/\s+[—-]\s+/);
    const description = rest.join(" — ").trim();
    const [rawName, rawType] = head.split(":").map((part) => part.trim());
    const name = rawName.replace(/\s+/g, "_");
    const type = (rawType || "text").toLowerCase();
    if (!FIELD_NAME.test(name)) {
      errors.push(`Line ${index + 1}: use a name of letters, digits and underscores, starting with a letter.`);
      return;
    }
    if (!(FIELD_TYPES as readonly string[]).includes(type)) {
      errors.push(`Line ${index + 1}: type must be ${FIELD_TYPES.join(", ")}.`);
      return;
    }
    if (names.has(name.toLowerCase())) {
      errors.push(`Line ${index + 1}: “${name}” is listed twice.`);
      return;
    }
    names.add(name.toLowerCase());
    fields.push({ name, type: type as FieldType, ...(description ? { description } : {}) });
  });
  if (fields.length > LIMITS.fields) errors.push(`Extract at most ${LIMITS.fields} fields at a time.`);
  return { fields, errors };
}

export interface ResearchForm {
  kind: ResearchKind;
  title: string;
  text: string;
  dimensionsText: string;
  fieldsText: string;
  documentIds: number[];
  pipelineId: number | null;
}

/** The request body for a form, or the problems to fix first. */
export function buildTaskPayload(form: ResearchForm): { payload: Record<string, unknown> | null; errors: string[] } {
  const info = kindInfo(form.kind);
  const errors: string[] = [];
  const payload: Record<string, unknown> = { kind: form.kind };
  if (form.title.trim()) payload.title = form.title.trim().slice(0, LIMITS.title);
  if (form.documentIds.length) payload.document_ids = [...form.documentIds];
  if (form.pipelineId != null) payload.pipeline_id = form.pipelineId;
  if (info.prompt) {
    const text = form.text.trim();
    const limit = LIMITS[info.prompt];
    if (!text) errors.push(`Enter the ${info.prompt}.`);
    else if (text.length > limit) errors.push(`Keep the ${info.prompt} under ${limit} characters.`);
    else payload[info.prompt] = text;
  }
  if (form.kind === "compare") {
    if (form.documentIds.length < LIMITS.compareMin || form.documentIds.length > LIMITS.compareMax) {
      errors.push(`Choose ${LIMITS.compareMin}–${LIMITS.compareMax} documents to compare.`);
    }
    const dimensions = parseDimensions(form.dimensionsText);
    if (dimensions.length > LIMITS.dimensions) errors.push(`Use at most ${LIMITS.dimensions} dimensions.`);
    if (dimensions.some((name) => name.length > LIMITS.dimension)) errors.push(`Keep each dimension under ${LIMITS.dimension} characters.`);
    if (dimensions.length) payload.dimensions = dimensions;
  }
  if (form.kind === "extract") {
    const { fields, errors: fieldErrors } = parseFieldSpecs(form.fieldsText);
    errors.push(...fieldErrors);
    if (!fields.length && !fieldErrors.length) errors.push("Name at least one field to extract.");
    payload.fields = fields;
  }
  return errors.length ? { payload: null, errors } : { payload, errors: [] };
}

/** The evidence objects for `ids`, in the order given (unknown ids skipped). */
export function evidenceFor(evidence: readonly Evidence[] | null | undefined, ids: readonly number[]): Evidence[] {
  const byId = new Map((evidence ?? []).map((item) => [item.citation_id, item] as const));
  return ids.map((id) => byId.get(id)).filter((item): item is Evidence => item != null);
}

/** Cited passages first, then the rest, each group in citation order. */
export function orderedEvidence(evidence: readonly Evidence[] | null | undefined): Evidence[] {
  const list = [...(evidence ?? [])];
  return [...list.filter((item) => item.cited), ...list.filter((item) => !item.cited)];
}

export function fieldValueText(value: unknown): string {
  if (value == null) return "—";
  if (Array.isArray(value)) return value.length ? value.map(String).join("; ") : "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export function fieldStatusText(status: string): string {
  return ({ found: "Found", not_found: "Not stated", uncited: "Dropped: no source cited", invalid: "Dropped: wrong type" } as Record<string, string>)[status] ?? status;
}

export function citationList(ids: readonly number[] | null | undefined): string {
  return (ids ?? []).map((id) => `[${id}]`).join(" ");
}
