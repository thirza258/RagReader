import type { Evidence } from "../types/index.ts";

/**
 * Citation markers in an answer: `[1]`, `[1, 2]`, `[1][3]` (PRD §13).
 *
 * The answer is markdown, so markers are found in the parsed tree rather than
 * in the raw string: text inside code spans, code blocks, links and raw HTML
 * never reaches a `text` node, so it is never turned into a button. A group
 * becomes a marker only when every number in it is a citation the answer
 * actually has; anything else (`[7]` with five sources, `[1, 9]`) stays text.
 */

export type CitationSegment =
  | { type: "text"; value: string }
  | { type: "citation"; ids: number[]; raw: string };

const MARKER = /\[(\s*\d{1,4}\s*(?:,\s*\d{1,4}\s*)*)\]/g;

export function splitCitationMarkers(text: string, validIds: ReadonlySet<number>): CitationSegment[] {
  const segments: CitationSegment[] = [];
  let last = 0;
  let pendingText = "";
  for (const match of text.matchAll(MARKER)) {
    const index = match.index ?? 0;
    const ids = match[1].split(",").map((part) => Number(part.trim()));
    if (ids.length === 0 || !ids.every((id) => Number.isInteger(id) && validIds.has(id))) continue;
    pendingText += text.slice(last, index);
    if (pendingText) segments.push({ type: "text", value: pendingText });
    pendingText = "";
    segments.push({ type: "citation", ids: [...new Set(ids)], raw: match[0] });
    last = index + match[0].length;
  }
  pendingText += text.slice(last);
  if (pendingText) segments.push({ type: "text", value: pendingText });
  return segments;
}

/** Every distinct, valid citation number in the text, in order of appearance. */
export function citedIds(text: string, validIds: ReadonlySet<number>): number[] {
  const seen: number[] = [];
  for (const segment of splitCitationMarkers(text, validIds)) {
    if (segment.type === "citation") for (const id of segment.ids) if (!seen.includes(id)) seen.push(id);
  }
  return seen;
}

/** The minimal mdast shape the walker needs; real trees carry more fields. */
export interface MdNode {
  type: string;
  value?: string;
  children?: MdNode[];
  data?: Record<string, unknown>;
  [key: string]: unknown;
}

/** The hast element a marker becomes; `AnswerMarkdown` renders it as buttons. */
export const CITATION_ELEMENT = "cite";
export const CITATION_IDS_PROPERTY = "dataCitationIds";

/** Nodes whose text must stay as written: links would nest buttons in anchors. */
const SKIP_PARENTS = new Set(["link", "linkReference", "definition", "code", "inlineCode", "html"]);

function citationNode(ids: number[], raw: string): MdNode {
  return {
    type: "citationMarker",
    data: {
      hName: CITATION_ELEMENT,
      hProperties: { [CITATION_IDS_PROPERTY]: ids.join(",") },
    },
    children: [{ type: "text", value: raw }],
  };
}

function transformChildren(parent: MdNode, validIds: ReadonlySet<number>) {
  const children = parent.children;
  if (!children || children.length === 0) return;
  const next: MdNode[] = [];
  let changed = false;
  for (const child of children) {
    if (child.type === "text" && typeof child.value === "string") {
      const segments = splitCitationMarkers(child.value, validIds);
      if (segments.length === 1 && segments[0].type === "text") {
        next.push(child);
        continue;
      }
      changed = true;
      for (const segment of segments) {
        next.push(segment.type === "text" ? { type: "text", value: segment.value } : citationNode(segment.ids, segment.raw));
      }
      continue;
    }
    if (!SKIP_PARENTS.has(child.type)) transformChildren(child, validIds);
    next.push(child);
  }
  if (changed) parent.children = next;
}

/** Turns markers in an mdast tree into citation nodes, in place. */
export function transformCitationTree(tree: MdNode, validIds: ReadonlySet<number>): MdNode {
  if (!SKIP_PARENTS.has(tree.type)) transformChildren(tree, validIds);
  return tree;
}

export interface CitationPluginOptions {
  validIds: ReadonlySet<number>;
}

/** A remark plugin (react-markdown `remarkPlugins`) for the transform above. */
export function remarkCitationMarkers(options?: CitationPluginOptions) {
  const validIds = options?.validIds ?? new Set<number>();
  return (tree: MdNode) => {
    transformCitationTree(tree, validIds);
  };
}

/** Parses the `data-citation-ids` value back into numbers. */
export function parseCitationIds(value: unknown): number[] {
  if (typeof value !== "string" && typeof value !== "number") return [];
  return String(value)
    .split(",")
    .map((part) => Number(part.trim()))
    .filter((id) => Number.isInteger(id) && id > 0);
}

/** Sources for display: cited ones first, each group in `[n]` order. */
export function orderSources(citations: readonly Evidence[] | null | undefined): { cited: Evidence[]; uncited: Evidence[] } {
  const sorted = [...(citations ?? [])].sort((a, b) => a.citation_id - b.citation_id);
  return {
    cited: sorted.filter((source) => source.cited),
    uncited: sorted.filter((source) => !source.cited),
  };
}

/** "Attention Is All You Need, page 4" / "pages 4–5" for labels. */
export function describeSource(source: Pick<Evidence, "document_title" | "page_number" | "page_end">): string {
  const title = source.document_title || "Untitled document";
  if (source.page_number == null) return title;
  if (source.page_end != null && source.page_end !== source.page_number) {
    return `${title}, pages ${source.page_number}–${source.page_end}`;
  }
  return `${title}, page ${source.page_number}`;
}
