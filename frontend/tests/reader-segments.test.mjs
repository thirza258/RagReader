import assert from "node:assert/strict";
import { test } from "node:test";
import {
  buildReaderBlocks,
  codePointsToUtf16,
  findMatches,
  locateEvidenceRange,
  normalizePages,
  pageAtOffset,
  resolvePages,
} from "../src/features/reader/lib/segments.ts";

// Two PDF pages joined with "\n\n", as the backend stores them.
const PAGE_1 = "Retrieval augmented generation.";
const PAGE_2 = "Dense retrieval embeds every chunk.";
const TEXT = `${PAGE_1}\n\n${PAGE_2}`;
const PAGES = [
  { number: 1, start: 0, end: PAGE_1.length },
  { number: 2, start: PAGE_1.length + 2, end: TEXT.length },
];

const text = (segment) => TEXT.slice(segment.start, segment.end);

test("page blocks keep the separator with the page before", () => {
  const blocks = buildReaderBlocks({ textLength: TEXT.length, pages: PAGES });
  assert.deepEqual(blocks.map((b) => [b.page, b.start, b.end]), [[1, 0, PAGE_1.length + 2], [2, PAGE_1.length + 2, TEXT.length]]);
  assert.deepEqual(blocks.map((b) => b.segments.length), [1, 1]);
  assert.deepEqual(buildReaderBlocks({ textLength: 5 }).map((b) => [b.page, b.start, b.end]), [[null, 0, 5]]);
});

test("a highlight across a page boundary is cut at the page break", () => {
  const start = TEXT.indexOf("generation");
  const end = TEXT.indexOf(" embeds");
  const blocks = buildReaderBlocks({ textLength: TEXT.length, pages: PAGES, highlight: { start, end } });
  const highlighted = blocks.flatMap((b) => b.segments.filter((s) => s.highlight).map((s) => [b.page, text(s)]));
  assert.deepEqual(highlighted, [[1, "generation.\n\n"], [2, "Dense retrieval"]]);
  const plain = blocks.flatMap((b) => b.segments.filter((s) => !s.highlight).map(text));
  assert.deepEqual(plain, ["Retrieval augmented ", " embeds every chunk."]);
});

test("search matches split segments and combine with the highlight", () => {
  const { matches } = findMatches(TEXT, "RETRIEVAL");
  assert.deepEqual(matches.map((m) => TEXT.slice(m.start, m.end)), ["Retrieval", "retrieval"]);
  const highlight = { start: TEXT.indexOf("Dense"), end: TEXT.length };
  const blocks = buildReaderBlocks({ textLength: TEXT.length, pages: PAGES, highlight, matches });
  const page2 = blocks[1].segments.map((s) => [text(s), s.highlight, s.match]);
  assert.deepEqual(page2, [
    ["Dense ", true, -1],
    ["retrieval", true, 1],
    [" embeds every chunk.", true, -1],
  ]);
  assert.deepEqual(blocks[0].segments.map((s) => [text(s), s.match]), [["Retrieval", 0], [" augmented generation.\n\n", -1]]);
});

test("a match crossing a page boundary is marked in both blocks", () => {
  const blocks = buildReaderBlocks({ textLength: TEXT.length, pages: PAGES, matches: [{ start: PAGE_1.length - 1, end: PAGE_1.length + 5 }] });
  assert.deepEqual(blocks.map((b) => b.segments.filter((s) => s.match === 0).map(text)), [[".\n\n"], ["Den"]]);
});

test("search is literal, capped and empty for blank queries", () => {
  assert.deepEqual(findMatches("a.b a+b", ".").matches, [{ start: 1, end: 2 }]);
  assert.deepEqual(findMatches("aaaa", "a", 2), { matches: [{ start: 0, end: 1 }, { start: 1, end: 2 }], truncated: true });
  assert.deepEqual(findMatches(TEXT, "   ").matches, []);
});

test("invalid, unsorted and overlapping pages are normalised", () => {
  assert.deepEqual(
    normalizePages([{ number: 2, start: 10, end: 30 }, { number: 1, start: 0, end: 12 }, { number: 3, start: 50, end: 40 }, { number: 4, start: 25, end: 99 }], 35),
    [{ number: 1, start: 0, end: 12 }, { number: 2, start: 12, end: 30 }, { number: 4, start: 30, end: 35 }],
  );
  assert.equal(pageAtOffset(PAGES, PAGE_1.length + 3), 2);
});

test("evidence offsets are used when the text there matches", () => {
  const start = TEXT.indexOf("Dense");
  const range = locateEvidenceRange(TEXT, { char_start: start, char_end: TEXT.length, text: PAGE_2 });
  assert.deepEqual(range, { start, end: TEXT.length, method: "offsets" });
});

test("evidence without offsets is found by its text, tolerating whitespace", () => {
  assert.equal(locateEvidenceRange(TEXT, { char_start: null, char_end: null, text: PAGE_2 }).method, "exact");
  const flexible = locateEvidenceRange(TEXT, { char_start: null, char_end: null, text: "generation.  Dense\nretrieval" });
  assert.equal(flexible.method, "flexible");
  assert.equal(TEXT.slice(flexible.start, flexible.end), "generation.\n\nDense retrieval");
  assert.equal(locateEvidenceRange(TEXT, { char_start: null, char_end: null, text: "not in the document at all" }), null);
});

test("code-point offsets are converted after astral characters", () => {
  // "𝐱" is one code point but two UTF-16 units, so Python offsets after it are one short.
  const astral = "Let 𝐱 be a vector. The key passage follows here.";
  const passage = "The key passage";
  const unitStart = astral.indexOf(passage);
  const pointStart = [...astral.slice(0, unitStart)].length;
  assert.equal(pointStart, unitStart - 1);
  assert.deepEqual(codePointsToUtf16(astral, [pointStart, pointStart + passage.length]), [unitStart, unitStart + passage.length]);
  const range = locateEvidenceRange(astral, { char_start: pointStart, char_end: pointStart + passage.length, text: passage });
  assert.deepEqual(range, { start: unitStart, end: unitStart + passage.length, method: "converted-offsets" });
});

test("page spans in code points are re-based when they line up better", () => {
  const first = "Page one has 𝐱.";
  const second = "Page two.";
  const doc = `${first}\n\n${second}`;
  const points = (s) => [...s].length;
  const pagesInPoints = [
    { number: 1, start: 0, end: points(first) },
    { number: 2, start: points(first) + 2, end: points(doc) },
  ];
  assert.deepEqual(resolvePages(doc, pagesInPoints), [
    { number: 1, start: 0, end: first.length },
    { number: 2, start: first.length + 2, end: doc.length },
  ]);
  assert.deepEqual(resolvePages(TEXT, PAGES), PAGES, "plain text needs no conversion");
});
