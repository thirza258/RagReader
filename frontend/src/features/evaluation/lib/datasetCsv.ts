import type { DatasetItemInput, ExpectedSource, HistoryTurn } from "../types/index.ts";

/**
 * Dataset files (docs/prd-implementation.md, Phase 4 "CSV format"): an
 * RFC 4180 reader, the compact source references (`12#p4; 14#c345,10234-10746`),
 * JSON imports, item validation that mirrors the server's rules, and the
 * export-style CSV writer. The server validates again on import; this is
 * what lets the import preview show every problem with its row first.
 */

export const CSV_COLUMNS = ["item_id", "question", "expected_answer", "expected_sources", "tags", "metadata", "history"] as const;
export type CsvColumn = (typeof CSV_COLUMNS)[number];

export const ITEM_LIMITS = {
  question: 4000,
  expectedAnswer: 20000,
  sources: 20,
  tags: 20,
  tagChars: 50,
  history: 6,
  historyChars: 4000,
  metadataBytes: 8192,
  sourceText: 1000,
  items: 2000,
} as const;

export const ITEM_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/;

const SOURCE_KEYS = new Set(["document_id", "document_title", "chunk_id", "index_version_id", "char_start", "char_end", "page", "page_end", "text"]);
const KNOWN_COLUMNS = new Set<string>(CSV_COLUMNS);

export interface FieldError {
  field: string;
  message: string;
}

/** `row` is the 1-based data row (the header is row 0), i.e. the item's index + 1. */
export interface RowError extends FieldError {
  row: number;
}

export interface ParsedDataset {
  format: "csv" | "json";
  /** Valid rows only, in file order. */
  items: DatasetItemInput[];
  /** Data rows read (valid or not). */
  rows: number;
  errors: RowError[];
  ignoredColumns: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function utf8Length(text: string): number {
  return new TextEncoder().encode(text).length;
}

// ── CSV reading ─────────────────────────────────────────────────────────────

export interface CsvRows {
  rows: string[][];
  /** A quoted cell was still open at the end of the text. */
  unterminated: boolean;
}

/**
 * RFC 4180 rows: `,` between cells, `"` quotes with `""` for a quote, LF, CRLF
 * (or a lone CR) between rows, line breaks inside quoted cells, a leading
 * BOM ignored. Lenient where the RFC is not: a quote inside an unquoted cell
 * is kept as a character.
 */
export function parseCsvRows(text: string): CsvRows {
  const input = text.startsWith("\uFEFF") ? text.slice(1) : text;
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  let wasQuoted = false;
  let pending = false;
  let index = 0;
  while (index < input.length) {
    const char = input[index];
    if (quoted) {
      if (char === '"') {
        if (input[index + 1] === '"') {
          cell += '"';
          index += 2;
          continue;
        }
        quoted = false;
        index += 1;
        continue;
      }
      cell += char;
      index += 1;
      continue;
    }
    if (char === '"' && cell === "" && !wasQuoted) {
      quoted = true;
      wasQuoted = true;
      pending = true;
      index += 1;
      continue;
    }
    if (char === ",") {
      row.push(cell);
      cell = "";
      wasQuoted = false;
      pending = true;
      index += 1;
      continue;
    }
    if (char === "\r" || char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      wasQuoted = false;
      pending = false;
      index += char === "\r" && input[index + 1] === "\n" ? 2 : 1;
      continue;
    }
    cell += char;
    pending = true;
    index += 1;
  }
  if (pending || cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return { rows, unterminated: quoted };
}

// ── Sources ─────────────────────────────────────────────────────────────────

function optionalPositive(value: unknown, field: string, errors: string[]): number | null {
  if (value === null || value === undefined) return null;
  if (!isInteger(value) || value < 1) {
    errors.push(`${field} must be a positive whole number.`);
    return null;
  }
  return value;
}

/**
 * One expected source, checked like the server does and returned with every
 * key (`document_title` only when given: the server resolves it).
 */
export function normalizeSource(raw: unknown): { source: ExpectedSource | null; errors: string[] } {
  const errors: string[] = [];
  if (!isRecord(raw)) return { source: null, errors: ["Each source must be an object."] };
  for (const key of Object.keys(raw)) {
    if (!SOURCE_KEYS.has(key)) errors.push(`Unknown key “${key}”.`);
  }
  const title = typeof raw.document_title === "string" ? raw.document_title.trim() : "";
  let documentId: number | null = null;
  if (raw.document_id === null || raw.document_id === undefined) {
    if (!title) errors.push("Name a document (document_id or document_title).");
  } else if (!isInteger(raw.document_id) || raw.document_id < 1) {
    errors.push("document_id must be a positive whole number.");
  } else {
    documentId = raw.document_id;
  }
  const chunkId = optionalPositive(raw.chunk_id, "chunk_id", errors);
  const indexVersionId = optionalPositive(raw.index_version_id, "index_version_id", errors);

  let charStart: number | null = null;
  let charEnd: number | null = null;
  const hasStart = raw.char_start !== null && raw.char_start !== undefined;
  const hasEnd = raw.char_end !== null && raw.char_end !== undefined;
  if (hasStart !== hasEnd) {
    errors.push("Give both char_start and char_end, or neither.");
  } else if (hasStart) {
    if (!isInteger(raw.char_start) || !isInteger(raw.char_end) || raw.char_start < 0) {
      errors.push("char_start and char_end must be whole numbers from 0.");
    } else if (raw.char_start >= raw.char_end) {
      errors.push("char_end must be greater than char_start.");
    } else {
      charStart = raw.char_start;
      charEnd = raw.char_end;
    }
  }

  let page: number | null = null;
  let pageEnd: number | null = null;
  const hasPage = raw.page !== null && raw.page !== undefined;
  const hasPageEnd = raw.page_end !== null && raw.page_end !== undefined;
  if (hasPage) {
    if (!isInteger(raw.page) || raw.page < 1) {
      errors.push("page must be a whole number from 1.");
    } else {
      page = raw.page;
      pageEnd = page;
      if (hasPageEnd) {
        if (!isInteger(raw.page_end) || raw.page_end < page) {
          errors.push("page_end must be a whole number no smaller than page.");
        } else {
          pageEnd = raw.page_end;
        }
      }
    }
  } else if (hasPageEnd) {
    errors.push("page_end needs page.");
  }

  let text = "";
  if (raw.text !== null && raw.text !== undefined) {
    if (typeof raw.text !== "string") errors.push("text must be text.");
    else if (raw.text.length > ITEM_LIMITS.sourceText) errors.push(`text is longer than ${ITEM_LIMITS.sourceText} characters.`);
    else text = raw.text;
  }
  if (errors.length) return { source: null, errors };
  const source: ExpectedSource = {
    document_id: documentId,
    chunk_id: chunkId,
    index_version_id: indexVersionId,
    char_start: charStart,
    char_end: charEnd,
    page,
    page_end: pageEnd,
    text,
  };
  if (title) source.document_title = title;
  return { source, errors: [] };
}

/**
 * Compact references: `DOC[#SEL[,SEL…]]` separated by `;`, SEL being
 * `p<page>`, `p<page>-<page_end>`, `c<chunk_id>` or `<char_start>-<char_end>`.
 */
export function parseCompactSources(cell: string): { sources: ExpectedSource[]; errors: string[] } {
  const sources: ExpectedSource[] = [];
  const errors: string[] = [];
  const tokens = cell
    .split(";")
    .map((token) => token.trim())
    .filter(Boolean);
  for (const token of tokens) {
    const match = /^(\d+)\s*(?:#\s*(.*))?$/.exec(token);
    if (!match) {
      errors.push(`“${token}” is not a source reference (DOC, DOC#p4, DOC#p4-5, DOC#c345 or DOC#100-200).`);
      continue;
    }
    const raw: Record<string, unknown> = { document_id: Number(match[1]) };
    const selectors = (match[2] ?? "")
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
    if (match[2] !== undefined && selectors.length === 0) {
      errors.push(`“${token}” has an empty reference after #.`);
      continue;
    }
    let bad = false;
    for (const selector of selectors) {
      const pages = /^p(\d+)(?:\s*-\s*(\d+))?$/i.exec(selector);
      const chunk = /^c(\d+)$/i.exec(selector);
      const chars = /^(\d+)\s*-\s*(\d+)$/.exec(selector);
      const kind = pages ? "page" : chunk ? "chunk_id" : chars ? "char_start" : null;
      if (!kind) {
        errors.push(`“${selector}” in “${token}” is not p<page>, p<page>-<page>, c<chunk id> or <start>-<end>.`);
        bad = true;
        break;
      }
      if (raw[kind] !== undefined) {
        errors.push(`“${token}” gives the ${kind === "page" ? "pages" : kind === "chunk_id" ? "chunk" : "character range"} twice.`);
        bad = true;
        break;
      }
      if (pages) {
        raw.page = Number(pages[1]);
        raw.page_end = pages[2] !== undefined ? Number(pages[2]) : Number(pages[1]);
      } else if (chunk) {
        raw.chunk_id = Number(chunk[1]);
      } else if (chars) {
        raw.char_start = Number(chars[1]);
        raw.char_end = Number(chars[2]);
      }
    }
    if (bad) continue;
    const normalized = normalizeSource(raw);
    if (normalized.source) sources.push(normalized.source);
    else errors.push(...normalized.errors.map((message) => `${token}: ${message}`));
  }
  return { sources, errors };
}

/** An `expected_sources` cell: empty, a JSON array, or compact references. */
export function parseSourcesCell(cell: string): { sources: unknown[]; errors: string[] } {
  const text = cell.trim();
  if (!text) return { sources: [], errors: [] };
  if (text.startsWith("[")) {
    try {
      const value = JSON.parse(text);
      if (!Array.isArray(value)) return { sources: [], errors: ["Expected a JSON array of sources."] };
      return { sources: value, errors: [] };
    } catch {
      return { sources: [], errors: ["The JSON list of sources is not valid JSON."] };
    }
  }
  return parseCompactSources(text);
}

/** "12#p4; 14#c345,10234-10746", or null when a source needs JSON (text, index version, title only). */
export function formatCompactSources(sources: readonly ExpectedSource[]): string | null {
  const parts: string[] = [];
  for (const source of sources) {
    if (source.document_id == null || source.text || source.index_version_id != null) return null;
    const selectors: string[] = [];
    if (source.page != null) selectors.push(source.page_end != null && source.page_end !== source.page ? `p${source.page}-${source.page_end}` : `p${source.page}`);
    if (source.chunk_id != null) selectors.push(`c${source.chunk_id}`);
    if (source.char_start != null && source.char_end != null) selectors.push(`${source.char_start}-${source.char_end}`);
    parts.push(selectors.length ? `${source.document_id}#${selectors.join(",")}` : String(source.document_id));
  }
  return parts.join("; ");
}

/** "Paper A · pp. 4–5 · chunk 345 · chars 100–200". */
export function describeSource(source: ExpectedSource, titleFor?: (documentId: number) => string | null | undefined): string {
  const title =
    source.document_title || (source.document_id != null ? titleFor?.(source.document_id) : null) || (source.document_id != null ? `Document ${source.document_id}` : "Unknown document");
  const parts = [title];
  if (source.page != null) parts.push(source.page_end != null && source.page_end !== source.page ? `pp. ${source.page}–${source.page_end}` : `p. ${source.page}`);
  if (source.chunk_id != null) parts.push(`chunk ${source.chunk_id}`);
  if (source.char_start != null && source.char_end != null) parts.push(`chars ${source.char_start}–${source.char_end}`);
  return parts.join(" · ");
}

// ── Items ───────────────────────────────────────────────────────────────────

/**
 * One item checked against the server's rules (question 1–4000 characters,
 * item id pattern, ≤ 20 sources, ≤ 20 tags of 1–50 characters, ≤ 6 history
 * turns, metadata a JSON object ≤ 8 KB) and normalised the way the server
 * stores it. Returns the item, or null with one message per field.
 */
export function validateItemInput(raw: unknown): { item: DatasetItemInput | null; errors: FieldError[] } {
  const errors: FieldError[] = [];
  if (!isRecord(raw)) return { item: null, errors: [{ field: "item", message: "Each item must be an object." }] };

  let itemId: string | undefined;
  if (raw.item_id !== undefined && raw.item_id !== null && raw.item_id !== "") {
    if (typeof raw.item_id !== "string" || !ITEM_ID_PATTERN.test(raw.item_id)) {
      errors.push({ field: "item_id", message: "Use 1–64 letters, digits, _ . : or -, starting with a letter or digit." });
    } else {
      itemId = raw.item_id;
    }
  }

  const question = typeof raw.question === "string" ? raw.question.trim() : "";
  if (typeof raw.question !== "string" && raw.question !== undefined && raw.question !== null) errors.push({ field: "question", message: "The question must be text." });
  else if (!question) errors.push({ field: "question", message: "The question may not be blank." });
  else if (question.length > ITEM_LIMITS.question) errors.push({ field: "question", message: `The question is longer than ${ITEM_LIMITS.question} characters.` });

  let expectedAnswer = "";
  if (raw.expected_answer !== undefined && raw.expected_answer !== null) {
    if (typeof raw.expected_answer !== "string") errors.push({ field: "expected_answer", message: "The expected answer must be text." });
    else if (raw.expected_answer.trim().length > ITEM_LIMITS.expectedAnswer) errors.push({ field: "expected_answer", message: `The expected answer is longer than ${ITEM_LIMITS.expectedAnswer.toLocaleString("en-US")} characters.` });
    else expectedAnswer = raw.expected_answer.trim();
  }

  const sources: ExpectedSource[] = [];
  if (raw.expected_sources !== undefined && raw.expected_sources !== null) {
    if (!Array.isArray(raw.expected_sources)) {
      errors.push({ field: "expected_sources", message: "Expected a list of sources." });
    } else if (raw.expected_sources.length > ITEM_LIMITS.sources) {
      errors.push({ field: "expected_sources", message: `At most ${ITEM_LIMITS.sources} expected sources.` });
    } else {
      const messages: string[] = [];
      raw.expected_sources.forEach((entry, index) => {
        const normalized = normalizeSource(entry);
        if (normalized.source) sources.push(normalized.source);
        else messages.push(...normalized.errors.map((message) => `Source ${index + 1}: ${message}`));
      });
      if (messages.length) errors.push({ field: "expected_sources", message: messages.join(" ") });
    }
  }

  const tags: string[] = [];
  if (raw.tags !== undefined && raw.tags !== null) {
    if (!Array.isArray(raw.tags) || raw.tags.some((tag) => typeof tag !== "string")) {
      errors.push({ field: "tags", message: "Tags must be a list of text." });
    } else {
      for (const tag of raw.tags as string[]) {
        const clean = tag.trim();
        if (!clean) continue;
        if (clean.length > ITEM_LIMITS.tagChars) {
          errors.push({ field: "tags", message: `Tag “${clean.slice(0, 20)}…” is longer than ${ITEM_LIMITS.tagChars} characters.` });
          break;
        }
        if (!tags.includes(clean)) tags.push(clean);
      }
      if (tags.length > ITEM_LIMITS.tags) errors.push({ field: "tags", message: `At most ${ITEM_LIMITS.tags} tags.` });
    }
  }

  const history: HistoryTurn[] = [];
  if (raw.history !== undefined && raw.history !== null) {
    if (!Array.isArray(raw.history)) {
      errors.push({ field: "history", message: "History must be a list of turns." });
    } else if (raw.history.length > ITEM_LIMITS.history) {
      errors.push({ field: "history", message: `At most ${ITEM_LIMITS.history} history turns.` });
    } else {
      for (const turn of raw.history) {
        const role = isRecord(turn) ? turn.role : undefined;
        const content = isRecord(turn) && typeof turn.content === "string" ? turn.content : null;
        if ((role !== "user" && role !== "assistant") || content === null || !content.trim() || content.length > ITEM_LIMITS.historyChars) {
          errors.push({ field: "history", message: `Each turn is {"role": "user" or "assistant", "content": 1–${ITEM_LIMITS.historyChars} characters}.` });
          break;
        }
        history.push({ role, content });
      }
    }
  }

  let metadata: Record<string, unknown> = {};
  if (raw.metadata !== undefined && raw.metadata !== null) {
    if (!isRecord(raw.metadata)) errors.push({ field: "metadata", message: "Metadata must be a JSON object." });
    else if (utf8Length(JSON.stringify(raw.metadata)) > ITEM_LIMITS.metadataBytes) errors.push({ field: "metadata", message: "Metadata is larger than 8 KB." });
    else metadata = raw.metadata;
  }

  if (errors.length) return { item: null, errors };
  const item: DatasetItemInput = { question, expected_answer: expectedAnswer, expected_sources: sources, history, tags, metadata };
  if (itemId) item.item_id = itemId;
  return { item, errors: [] };
}

function parseJsonCell(cell: string, field: "metadata" | "history"): { value: unknown; error: string | null } {
  const text = cell.trim();
  if (!text) return { value: field === "metadata" ? {} : [], error: null };
  try {
    return { value: JSON.parse(text), error: null };
  } catch {
    return { value: null, error: field === "metadata" ? "Metadata must be empty or a JSON object." : "History must be empty or a JSON list of turns." };
  }
}

function checkUniqueIds(items: { row: number; item: DatasetItemInput }[], errors: RowError[]) {
  const seen = new Map<string, number>();
  for (const { row, item } of items) {
    if (!item.item_id) continue;
    const first = seen.get(item.item_id);
    if (first !== undefined) errors.push({ row, field: "item_id", message: `Item id “${item.item_id}” is also used in row ${first}.` });
    else seen.set(item.item_id, row);
  }
}

function finish(format: "csv" | "json", parsed: { row: number; item: DatasetItemInput }[], rows: number, errors: RowError[], ignoredColumns: string[]): ParsedDataset {
  checkUniqueIds(parsed, errors);
  if (rows > ITEM_LIMITS.items) errors.push({ row: 0, field: "items", message: `A version holds at most ${ITEM_LIMITS.items.toLocaleString("en-US")} items.` });
  const badRows = new Set(errors.map((error) => error.row));
  errors.sort((a, b) => a.row - b.row);
  return { format, items: parsed.filter(({ row }) => !badRows.has(row)).map(({ item }) => item), rows, errors, ignoredColumns };
}

/** A dataset CSV (header row required, `question` column required). */
export function parseDatasetCsv(text: string): ParsedDataset {
  const { rows, unterminated } = parseCsvRows(text);
  const errors: RowError[] = [];
  if (unterminated) errors.push({ row: 0, field: "csv", message: "A quoted cell is not closed (a \" is missing)." });
  const filled = rows.filter((cells) => cells.some((cell) => cell.trim() !== ""));
  if (filled.length === 0) {
    errors.push({ row: 0, field: "csv", message: "The file is empty: it needs a header row and one row per question." });
    return { format: "csv", items: [], rows: 0, errors, ignoredColumns: [] };
  }
  const columns = new Map<CsvColumn, number>();
  const ignoredColumns: string[] = [];
  filled[0].forEach((name, index) => {
    const clean = name.trim();
    const key = clean.toLowerCase();
    if (KNOWN_COLUMNS.has(key) && !columns.has(key as CsvColumn)) columns.set(key as CsvColumn, index);
    else if (clean) ignoredColumns.push(clean);
  });
  if (!columns.has("question")) {
    errors.push({ row: 0, field: "question", message: "The header row needs a “question” column." });
    return { format: "csv", items: [], rows: filled.length - 1, errors, ignoredColumns };
  }

  const parsed: { row: number; item: DatasetItemInput }[] = [];
  filled.slice(1).forEach((cells, index) => {
    const row = index + 1;
    const cell = (column: CsvColumn) => {
      const at = columns.get(column);
      return at === undefined ? "" : (cells[at] ?? "");
    };
    const rowErrors: FieldError[] = [];
    const sources = parseSourcesCell(cell("expected_sources"));
    if (sources.errors.length) rowErrors.push({ field: "expected_sources", message: sources.errors.join(" ") });
    const metadata = parseJsonCell(cell("metadata"), "metadata");
    if (metadata.error) rowErrors.push({ field: "metadata", message: metadata.error });
    const history = parseJsonCell(cell("history"), "history");
    if (history.error) rowErrors.push({ field: "history", message: history.error });
    const candidate = {
      item_id: cell("item_id").trim() || undefined,
      question: cell("question"),
      expected_answer: cell("expected_answer"),
      expected_sources: sources.errors.length ? [] : sources.sources,
      tags: cell("tags").split(";"),
      metadata: metadata.error ? {} : metadata.value,
      history: history.error ? [] : history.value,
    };
    const checked = validateItemInput(candidate);
    rowErrors.push(...checked.errors);
    if (rowErrors.length) {
      for (const error of rowErrors) errors.push({ row, ...error });
      parsed.push({ row, item: checked.item ?? { question: candidate.question.trim() } });
    } else if (checked.item) {
      parsed.push({ row, item: checked.item });
    }
  });
  return finish("csv", parsed, filled.length - 1, errors, ignoredColumns);
}

/** A JSON import: the export object (`{"items": [...]}`) or a bare list of items. */
export function parseDatasetJson(text: string): ParsedDataset {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { format: "json", items: [], rows: 0, errors: [{ row: 0, field: "json", message: "The file is not valid JSON." }], ignoredColumns: [] };
  }
  const list = Array.isArray(data) ? data : isRecord(data) && Array.isArray(data.items) ? data.items : null;
  if (!list) {
    return {
      format: "json",
      items: [],
      rows: 0,
      errors: [{ row: 0, field: "json", message: "Expected a list of items, or an exported dataset with an “items” list." }],
      ignoredColumns: [],
    };
  }
  const errors: RowError[] = [];
  const parsed: { row: number; item: DatasetItemInput }[] = [];
  list.forEach((entry, index) => {
    const row = index + 1;
    const candidate = isRecord(entry)
      ? {
          item_id: entry.item_id,
          question: entry.question,
          expected_answer: entry.expected_answer,
          expected_sources: entry.expected_sources,
          tags: entry.tags,
          metadata: entry.metadata,
          history: entry.history,
        }
      : entry;
    const checked = validateItemInput(candidate);
    if (checked.errors.length) {
      for (const error of checked.errors) errors.push({ row, ...error });
      parsed.push({ row, item: { question: isRecord(entry) && typeof entry.question === "string" ? entry.question : "" } });
    } else if (checked.item) {
      parsed.push({ row, item: checked.item });
    }
  });
  return finish("json", parsed, list.length, errors, []);
}

/** By file name, else by the first character (`[` or `{` → JSON). */
export function detectFormat(text: string, fileName?: string | null): "csv" | "json" {
  const name = (fileName ?? "").toLowerCase();
  if (name.endsWith(".json")) return "json";
  if (name.endsWith(".csv")) return "csv";
  const first = text.replace(/^\uFEFF/, "").trimStart()[0];
  return first === "[" || first === "{" ? "json" : "csv";
}

export function parseDatasetFile(text: string, fileName?: string | null): ParsedDataset {
  return detectFormat(text, fileName) === "json" ? parseDatasetJson(text) : parseDatasetCsv(text);
}

// ── CSV writing ─────────────────────────────────────────────────────────────

function csvCell(value: string): string {
  return /[",\r\n]|^\s|\s$/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

/**
 * Items as the server exports them: every column, sources/metadata/history
 * as JSON, tags joined with "; ", CRLF line ends.
 */
export function toCsv(items: readonly DatasetItemInput[]): string {
  const lines = [CSV_COLUMNS.join(",")];
  for (const item of items) {
    const cells = [
      item.item_id ?? "",
      item.question ?? "",
      item.expected_answer ?? "",
      JSON.stringify(item.expected_sources ?? []),
      (item.tags ?? []).join("; "),
      JSON.stringify(item.metadata ?? {}),
      JSON.stringify(item.history ?? []),
    ];
    lines.push(cells.map(csvCell).join(","));
  }
  return `${lines.join("\r\n")}\r\n`;
}
