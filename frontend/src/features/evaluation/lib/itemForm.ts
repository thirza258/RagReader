import type { DraftSource, ExpectedSource } from "../types/index.ts";
import { ITEM_LIMITS, normalizeSource } from "./datasetCsv.ts";

/**
 * Form state for an item's expected sources: every number is edited as text
 * and checked with the same rules as an import (`normalizeSource`) when the
 * item is saved. Also turns a chat answer's evidence into expected sources.
 */

export interface SourceDraft {
  document_id: string;
  /** Kept for sources that name their document by title only. */
  document_title: string;
  page: string;
  page_end: string;
  chunk_id: string;
  char_start: string;
  char_end: string;
  /** Carried through unchanged (set when a source came from an answer). */
  index_version_id: number | null;
  text: string;
}

export function emptySourceDraft(documentId: number | null = null): SourceDraft {
  return {
    document_id: documentId != null ? String(documentId) : "",
    document_title: "",
    page: "",
    page_end: "",
    chunk_id: "",
    char_start: "",
    char_end: "",
    index_version_id: null,
    text: "",
  };
}

function text(value: number | null | undefined): string {
  return value == null ? "" : String(value);
}

export function toSourceDraft(source: ExpectedSource): SourceDraft {
  return {
    document_id: text(source.document_id),
    document_title: source.document_id == null ? (source.document_title ?? "") : "",
    page: text(source.page),
    page_end: source.page_end != null && source.page_end !== source.page ? text(source.page_end) : "",
    chunk_id: text(source.chunk_id),
    char_start: text(source.char_start),
    char_end: text(source.char_end),
    index_version_id: source.index_version_id ?? null,
    text: source.text ?? "",
  };
}

/** "" → null, "12" → 12, anything else → NaN (reported by the validation). */
function parseNumber(value: string): number | null {
  const clean = value.trim();
  if (!clean) return null;
  return /^-?\d+$/.test(clean) ? Number(clean) : Number.NaN;
}

/** The source to send, or the problems with it ("Source 2: …" is added by the caller). */
export function fromSourceDraft(draft: SourceDraft): { source: ExpectedSource | null; errors: string[] } {
  const raw: Record<string, unknown> = {
    document_id: parseNumber(draft.document_id),
    chunk_id: parseNumber(draft.chunk_id),
    index_version_id: draft.index_version_id,
    char_start: parseNumber(draft.char_start),
    char_end: parseNumber(draft.char_end),
    page: parseNumber(draft.page),
    page_end: parseNumber(draft.page_end),
    text: draft.text,
  };
  if (draft.document_id.trim() === "" && draft.document_title.trim()) raw.document_title = draft.document_title.trim();
  return normalizeSource(raw);
}

export function sourcesFromDrafts(drafts: readonly SourceDraft[]): { sources: ExpectedSource[]; errors: string[] } {
  const sources: ExpectedSource[] = [];
  const errors: string[] = [];
  drafts.forEach((draft, index) => {
    const result = fromSourceDraft(draft);
    if (result.source) sources.push(result.source);
    else errors.push(...result.errors.map((message) => `Source ${index + 1}: ${message}`));
  });
  return { sources, errors };
}

/** "a; b, c" → ["a", "b", "c"] (either separator; blanks and duplicates dropped). */
export function tagsFromText(value: string): string[] {
  const tags: string[] = [];
  for (const part of value.split(/[;,]/)) {
    const clean = part.trim();
    if (clean && !tags.includes(clean)) tags.push(clean);
  }
  return tags;
}

export function tagsText(tags: readonly string[] | null | undefined): string {
  return (tags ?? []).join(", ");
}

function sameSource(a: Pick<ExpectedSource, "document_id" | "chunk_id">, b: { document_id: number | null; chunk_id: number | string | null }): boolean {
  return a.document_id === b.document_id && a.chunk_id != null && String(a.chunk_id) === String(b.chunk_id);
}

/**
 * A chat answer's source as an expected source: the server's draft entry
 * for the same chunk when it has one, else built from the evidence (chunk,
 * index version, character range, pages, a quote of at most 1,000 chars).
 */
export function evidenceToExpected(evidence: DraftSource, drafted: readonly ExpectedSource[] = []): ExpectedSource {
  const match = drafted.find((source) => sameSource(source, evidence));
  if (match) return match;
  const chunk = typeof evidence.chunk_id === "number" ? evidence.chunk_id : /^\d+$/.test(String(evidence.chunk_id ?? "")) ? Number(evidence.chunk_id) : null;
  const hasRange = evidence.char_start != null && evidence.char_end != null && evidence.char_end > evidence.char_start;
  const page = evidence.page_number != null && evidence.page_number >= 1 ? evidence.page_number : null;
  return {
    document_id: evidence.document_id,
    chunk_id: chunk != null && chunk > 0 ? chunk : null,
    index_version_id: evidence.index_version_id ?? null,
    char_start: hasRange ? evidence.char_start : null,
    char_end: hasRange ? evidence.char_end : null,
    page,
    page_end: page != null ? Math.max(page, evidence.page_end ?? page) : null,
    text: (evidence.text ?? "").slice(0, ITEM_LIMITS.sourceText),
  };
}
