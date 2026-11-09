import type { PageSpan } from "../../documents/types/index.ts";

/**
 * Pure helpers behind the document reader (PRD §12): page blocks, search
 * matches and the highlighted evidence range, cut into render segments.
 *
 * Offsets from the backend (`pages`, `char_start`/`char_end`) may count
 * Unicode code points (Python string indices) while JavaScript strings count
 * UTF-16 units; the two differ after the first astral character, which PDFs
 * of papers often contain (mathematical letters). Every offset is therefore
 * checked against the text and converted when the conversion fits better.
 */

export interface TextRange {
  start: number;
  end: number;
}

const ASTRAL = /[\uD800-\uDBFF][\uDC00-\uDFFF]/;

export function hasAstralCharacters(text: string): boolean {
  return ASTRAL.test(text);
}

/** Converts code-point offsets to UTF-16 offsets in one pass over the text. */
export function codePointsToUtf16(text: string, offsets: readonly number[]): number[] {
  const order = offsets.map((offset, index) => [offset, index] as const).sort((a, b) => a[0] - b[0]);
  const result: number[] = new Array(offsets.length);
  let points = 0;
  let units = 0;
  for (const [target, index] of order) {
    while (points < target && units < text.length) {
      const code = text.charCodeAt(units);
      const pair = code >= 0xd800 && code <= 0xdbff && units + 1 < text.length && (text.charCodeAt(units + 1) & 0xfc00) === 0xdc00;
      units += pair ? 2 : 1;
      points += 1;
    }
    result[index] = points < target ? units + (target - points) : units;
  }
  return result;
}

/** Sorted, clamped, non-overlapping page spans; invalid entries dropped. */
export function normalizePages(pages: readonly PageSpan[] | null | undefined, textLength: number): PageSpan[] {
  if (!Array.isArray(pages)) return [];
  const valid = pages
    .filter((page) => page && Number.isFinite(page.start) && Number.isFinite(page.end) && Number.isFinite(page.number))
    .map((page) => ({
      number: page.number,
      start: Math.max(0, Math.min(textLength, Math.floor(page.start))),
      end: Math.max(0, Math.min(textLength, Math.floor(page.end))),
    }))
    .sort((a, b) => a.start - b.start || a.number - b.number);
  const result: PageSpan[] = [];
  let cursor = 0;
  for (const page of valid) {
    const start = Math.max(page.start, cursor);
    if (page.end <= start) continue;
    result.push({ number: page.number, start, end: page.end });
    cursor = page.end;
  }
  return result;
}

function alignedStarts(text: string, pages: readonly PageSpan[]): number {
  let score = 0;
  for (const page of pages) {
    if (page.start === 0 || text.slice(Math.max(0, page.start - 2), page.start) === "\n\n") score += 1;
  }
  return score;
}

/**
 * Page spans as UTF-16 offsets into `text`. Pages are joined with "\n\n", so
 * the reading whose page starts follow a blank line is the right one.
 */
export function resolvePages(text: string, pages: readonly PageSpan[] | null | undefined): PageSpan[] {
  if (!Array.isArray(pages) || pages.length === 0) return [];
  const raw = normalizePages(pages, text.length);
  if (!hasAstralCharacters(text)) return raw;
  const flat = pages.flatMap((page) => [page.start, page.end]);
  const converted = codePointsToUtf16(text, flat);
  const fromPoints = normalizePages(
    pages.map((page, i) => ({ number: page.number, start: converted[2 * i], end: converted[2 * i + 1] })),
    text.length,
  );
  return alignedStarts(text, fromPoints) > alignedStarts(text, raw) ? fromPoints : raw;
}

/** The page whose span contains `offset`, if any. */
export function pageAtOffset(pages: readonly PageSpan[], offset: number): number | null {
  for (const page of pages) if (offset >= page.start && offset < page.end) return page.number;
  return null;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
}

export interface MatchResult {
  matches: TextRange[];
  /** True when the limit cut the list short. */
  truncated: boolean;
}

/** Case-insensitive, non-overlapping matches of `query`. */
export function findMatches(text: string, query: string, limit = 1000): MatchResult {
  const needle = query.trim();
  if (!needle || !text) return { matches: [], truncated: false };
  const pattern = new RegExp(escapeRegExp(needle), "gi");
  const matches: TextRange[] = [];
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (matches.length >= limit) return { matches, truncated: true };
    matches.push({ start: match.index, end: match.index + match[0].length });
    if (match[0].length === 0) pattern.lastIndex += 1;
  }
  return { matches, truncated: false };
}

function words(value: string): string[] {
  return value.split(/\s+/).filter(Boolean);
}

/** Finds `needle` in `text` allowing any run of whitespace between words. */
function flexibleSearch(text: string, needle: string, maxWords = 1500): TextRange | null {
  const parts = words(needle).slice(0, maxWords);
  if (parts.length === 0) return null;
  const pattern = new RegExp(parts.map(escapeRegExp).join("\\s+"));
  const match = pattern.exec(text);
  return match ? { start: match.index, end: match.index + match[0].length } : null;
}

export type EvidenceMatchMethod = "offsets" | "converted-offsets" | "exact" | "flexible" | "prefix" | "unverified-offsets";

export interface EvidenceRange extends TextRange {
  method: EvidenceMatchMethod;
}

export interface EvidenceLike {
  char_start: number | null;
  char_end: number | null;
  text: string;
}

function validRange(start: unknown, end: unknown, length: number): start is number {
  return typeof start === "number" && typeof end === "number" && Number.isInteger(start) && Number.isInteger(end) && start >= 0 && end > start && end <= length;
}

/** Collapses whitespace runs but keeps their position, so a shifted window still differs. */
function collapseWhitespace(value: string): string {
  return value.replace(/\s+/g, " ");
}

/** 2: the slice is the evidence; 1: it starts like the evidence; 0: no match. */
function sliceScore(text: string, range: TextRange, evidenceText: string): number {
  const expected = collapseWhitespace(evidenceText);
  if (!expected.trim()) return 1;
  const actual = collapseWhitespace(text.slice(range.start, range.end));
  if (actual === expected || actual.trim() === expected.trim()) return 2;
  const probe = Math.min(48, expected.length, actual.length);
  return probe >= 8 && actual.slice(0, probe) === expected.slice(0, probe) ? 1 : 0;
}

/**
 * Where the evidence is in the text. Offsets win when the text there matches
 * the evidence (as given, or read as code points); otherwise the evidence text
 * is searched for, first exactly, then ignoring whitespace differences, then
 * by its opening words. In-range offsets are used unverified as a last resort.
 */
export function locateEvidenceRange(text: string, evidence: EvidenceLike | null | undefined): EvidenceRange | null {
  if (!evidence || !text) return null;
  const evidenceText = typeof evidence.text === "string" ? evidence.text : "";
  const { char_start: start, char_end: end } = evidence;
  const candidates: EvidenceRange[] = [];
  if (validRange(start, end, text.length)) candidates.push({ start, end: end as number, method: "offsets" });
  if (typeof start === "number" && typeof end === "number" && hasAstralCharacters(text)) {
    const [convertedStart, convertedEnd] = codePointsToUtf16(text, [start, end]);
    if (validRange(convertedStart, convertedEnd, text.length) && (convertedStart !== start || convertedEnd !== end)) {
      candidates.push({ start: convertedStart, end: convertedEnd, method: "converted-offsets" });
    }
  }
  const scored = candidates.map((candidate) => ({ candidate, score: sliceScore(text, candidate, evidenceText) }));
  for (const wanted of [2, 1]) {
    const hit = scored.find((entry) => entry.score === wanted);
    if (hit) return hit.candidate;
  }
  const trimmed = evidenceText.trim();
  if (trimmed) {
    const exact = text.indexOf(trimmed);
    if (exact !== -1) return { start: exact, end: exact + trimmed.length, method: "exact" };
    const flexible = flexibleSearch(text, trimmed);
    if (flexible) return { ...flexible, method: "flexible" };
    const opening = words(trimmed).slice(0, 12).join(" ");
    if (opening.length >= 16) {
      const prefix = flexibleSearch(text, opening);
      if (prefix) {
        return { start: prefix.start, end: Math.min(text.length, prefix.start + trimmed.length), method: "prefix" };
      }
    }
  }
  const raw = candidates.find((candidate) => candidate.method === "offsets");
  return raw ? { ...raw, method: "unverified-offsets" } : null;
}

export interface ReaderSegment extends TextRange {
  highlight: boolean;
  /** Index into the match list, or -1. */
  match: number;
}

export interface ReaderBlock extends TextRange {
  key: string;
  /** PDF page number, or null for text before the first page / non-PDFs. */
  page: number | null;
  segments: ReaderSegment[];
}

export interface BuildBlocksInput {
  textLength: number;
  pages?: readonly PageSpan[];
  highlight?: TextRange | null;
  matches?: readonly TextRange[];
}

function blockRanges(textLength: number, pages: readonly PageSpan[]): { key: string; page: number | null; start: number; end: number }[] {
  if (pages.length === 0) return textLength > 0 ? [{ key: "text", page: null, start: 0, end: textLength }] : [];
  const blocks: { key: string; page: number | null; start: number; end: number }[] = [];
  if (pages[0].start > 0) blocks.push({ key: "front", page: null, start: 0, end: pages[0].start });
  pages.forEach((page, i) => {
    // The "\n\n" between pages stays with the page before it.
    const end = i + 1 < pages.length ? pages[i + 1].start : textLength;
    if (end > page.start) blocks.push({ key: `page-${page.number}-${page.start}`, page: page.number, start: page.start, end });
  });
  return blocks;
}

/**
 * Splits the text into page blocks and each block into segments at page,
 * highlight and match boundaries. Adjacent segments with the same marks are
 * merged, so plain text stays in as few nodes as possible.
 */
export function buildReaderBlocks(input: BuildBlocksInput): ReaderBlock[] {
  const { textLength } = input;
  const pages = normalizePages(input.pages ?? [], textLength);
  const highlight =
    input.highlight && input.highlight.end > input.highlight.start
      ? { start: Math.max(0, input.highlight.start), end: Math.min(textLength, input.highlight.end) }
      : null;
  const matches = [...(input.matches ?? [])]
    .filter((match) => match.end > match.start && match.start >= 0 && match.end <= textLength)
    .sort((a, b) => a.start - b.start);

  let matchCursor = 0;
  return blockRanges(textLength, pages).map((block) => {
    const points = new Set<number>([block.start, block.end]);
    if (highlight) {
      if (highlight.start > block.start && highlight.start < block.end) points.add(highlight.start);
      if (highlight.end > block.start && highlight.end < block.end) points.add(highlight.end);
    }
    while (matchCursor < matches.length && matches[matchCursor].end <= block.start) matchCursor += 1;
    const blockMatches: number[] = [];
    for (let i = matchCursor; i < matches.length && matches[i].start < block.end; i += 1) {
      blockMatches.push(i);
      if (matches[i].start > block.start) points.add(matches[i].start);
      if (matches[i].end < block.end) points.add(matches[i].end);
    }
    const cuts = [...points].sort((a, b) => a - b);
    const segments: ReaderSegment[] = [];
    let local = 0;
    for (let i = 0; i + 1 < cuts.length; i += 1) {
      const start = cuts[i];
      const end = cuts[i + 1];
      if (end <= start) continue;
      const inHighlight = !!highlight && start >= highlight.start && end <= highlight.end;
      while (local < blockMatches.length && matches[blockMatches[local]].end <= start) local += 1;
      const candidate = local < blockMatches.length ? blockMatches[local] : -1;
      const match = candidate !== -1 && matches[candidate].start <= start && matches[candidate].end >= end ? candidate : -1;
      const previous = segments[segments.length - 1];
      if (previous && previous.highlight === inHighlight && previous.match === match && previous.end === start) {
        previous.end = end;
      } else {
        segments.push({ start, end, highlight: inHighlight, match });
      }
    }
    return { key: block.key, page: block.page, start: block.start, end: block.end, segments };
  });
}
