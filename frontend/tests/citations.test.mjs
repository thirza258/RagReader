import assert from "node:assert/strict";
import { test } from "node:test";
import {
  citedIds,
  describeSource,
  orderSources,
  parseCitationIds,
  remarkCitationMarkers,
  splitCitationMarkers,
  transformCitationTree,
} from "../src/features/chat/lib/citations.ts";

const ids = (...values) => new Set(values);

test("a single marker becomes a citation between text segments", () => {
  assert.deepEqual(splitCitationMarkers("RAG grounds answers [1].", ids(1, 2)), [
    { type: "text", value: "RAG grounds answers " },
    { type: "citation", ids: [1], raw: "[1]" },
    { type: "text", value: "." },
  ]);
});

test("lists keep every id, with or without spaces", () => {
  assert.deepEqual(splitCitationMarkers("Both [1, 2] and [2,3].", ids(1, 2, 3)), [
    { type: "text", value: "Both " },
    { type: "citation", ids: [1, 2], raw: "[1, 2]" },
    { type: "text", value: " and " },
    { type: "citation", ids: [2, 3], raw: "[2,3]" },
    { type: "text", value: "." },
  ]);
});

test("adjacent markers stay separate citations", () => {
  assert.deepEqual(splitCitationMarkers("Claim[1][3]", ids(1, 2, 3)), [
    { type: "text", value: "Claim" },
    { type: "citation", ids: [1], raw: "[1]" },
    { type: "citation", ids: [3], raw: "[3]" },
  ]);
  assert.deepEqual(citedIds("a [3] b [1][3] c [2, 1]", ids(1, 2, 3)), [3, 1, 2]);
});

test("out-of-range and non-numeric markers stay plain text", () => {
  const text = "See [7], [0], [1, 9], [a] and [ ] here.";
  assert.deepEqual(splitCitationMarkers(text, ids(1, 2, 3, 4, 5)), [{ type: "text", value: text }]);
  assert.deepEqual(splitCitationMarkers("[2] then [6]", ids(1, 2)), [
    { type: "citation", ids: [2], raw: "[2]" },
    { type: "text", value: " then [6]" },
  ]);
});

// Hand-built mdast, shaped like remark-parse's output for
// "Grounded [1] and `code [2]`, **bold [2]** [link [1]](http://x)\n\n```\nfenced [1]\n```"
function sampleTree() {
  return {
    type: "root",
    children: [
      {
        type: "paragraph",
        children: [
          { type: "text", value: "Grounded [1] and " },
          { type: "inlineCode", value: "code [2]" },
          { type: "text", value: ", " },
          { type: "strong", children: [{ type: "text", value: "bold [2]" }] },
          { type: "text", value: " " },
          { type: "link", url: "http://x", children: [{ type: "text", value: "link [1]" }] },
        ],
      },
      { type: "code", lang: null, value: "fenced [1]" },
      { type: "html", value: "<b>[1]</b>" },
    ],
  };
}

test("markers inside code spans, code blocks, links and HTML are untouched", () => {
  const tree = transformCitationTree(sampleTree(), ids(1, 2));
  const [paragraph, code, html] = tree.children;
  assert.deepEqual(paragraph.children.find((node) => node.type === "inlineCode"), { type: "inlineCode", value: "code [2]" });
  assert.deepEqual(code, { type: "code", lang: null, value: "fenced [1]" });
  assert.deepEqual(html, { type: "html", value: "<b>[1]</b>" });
  const link = paragraph.children.find((node) => node.type === "link");
  assert.deepEqual(link.children, [{ type: "text", value: "link [1]" }]);
});

test("markers in text, including nested emphasis, become citation nodes", () => {
  const tree = sampleTree();
  remarkCitationMarkers({ validIds: ids(1, 2) })(tree);
  const paragraph = tree.children[0];
  assert.deepEqual(paragraph.children.slice(0, 2), [
    { type: "text", value: "Grounded " },
    {
      type: "citationMarker",
      data: { hName: "cite", hProperties: { dataCitationIds: "1" } },
      children: [{ type: "text", value: "[1]" }],
    },
  ]);
  const strong = paragraph.children.find((node) => node.type === "strong");
  assert.equal(strong.children[1].type, "citationMarker");
  assert.equal(strong.children[1].data.hProperties.dataCitationIds, "2");
});

test("citation ids round-trip through the element property", () => {
  assert.deepEqual(parseCitationIds("1,2"), [1, 2]);
  assert.deepEqual(parseCitationIds(3), [3]);
  assert.deepEqual(parseCitationIds(undefined), []);
});

test("sources list cited evidence first, each group in [n] order", () => {
  const source = (citation_id, cited) => ({ citation_id, cited, document_title: "Doc", page_number: null, page_end: null });
  const { cited, uncited } = orderSources([source(3, true), source(2, false), source(1, true), source(4, false)]);
  assert.deepEqual(cited.map((s) => s.citation_id), [1, 3]);
  assert.deepEqual(uncited.map((s) => s.citation_id), [2, 4]);
  assert.equal(describeSource({ document_title: "Paper", page_number: 4, page_end: 5 }), "Paper, pages 4–5");
  assert.equal(describeSource({ document_title: "Paper", page_number: 4, page_end: 4 }), "Paper, page 4");
});
