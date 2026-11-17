import assert from "node:assert/strict";
import { test } from "node:test";
import {
  KINDS, buildTaskPayload, citationList, evidenceFor, fieldStatusText, fieldValueText, isActive, kindInfo,
  orderedEvidence, parseDimensions, parseFieldSpecs, verdictText, verdictTone,
} from "../src/features/research/lib/research.ts";
import { isProtectedApiPath } from "../src/features/auth/lib/unauthorized.ts";

const form = (overrides = {}) => ({
  kind: "verify_claim", title: "", text: "", dimensionsText: "", fieldsText: "", documentIds: [], pipelineId: null, ...overrides,
});

test("every research kind has a label and the server's id", () => {
  assert.deepEqual(KINDS.map((kind) => kind.id), ["verify_claim", "ask", "compare", "extract", "contradictions", "report"]);
  assert.equal(kindInfo("nope").id, "verify_claim");
  assert.equal(kindInfo("contradictions").prompt, "topic");
});

test("verdict wording and tone", () => {
  assert.equal(verdictText("supported", "moderate"), "Supported · moderate confidence");
  assert.equal(verdictText("insufficient_evidence", "low"), "Insufficient evidence");
  assert.equal(verdictTone("contradicted"), "bad");
  assert.equal(verdictTone("mixed"), "mixed");
  assert.equal(verdictTone(undefined), "unknown");
  assert.equal(isActive("running"), true);
  assert.equal(isActive("completed"), false);
});

test("dimensions are split on commas and lines, de-duplicated without case", () => {
  assert.deepEqual(parseDimensions("methodology, Dataset\n dataset ,  evaluation  metrics"), ["methodology", "Dataset", "evaluation metrics"]);
  assert.deepEqual(parseDimensions(" , \n"), []);
});

test("field specs: name, optional type and description, with line-numbered errors", () => {
  const { fields, errors } = parseFieldSpecs("dataset: text — the benchmark\nsamples: number\nmetrics:list\n\nbad name!: text\nyear: date\nsamples");
  assert.deepEqual(fields, [
    { name: "dataset", type: "text", description: "the benchmark" },
    { name: "samples", type: "number" },
    { name: "metrics", type: "list" },
  ]);
  assert.equal(errors.length, 3);
  assert.match(errors[0], /^Line 5/);
  assert.match(errors[1], /type must be/);
  assert.match(errors[2], /listed twice/);
});

test("building a payload checks each kind's input", () => {
  assert.deepEqual(buildTaskPayload(form()).errors, ["Enter the claim."]);
  const claim = buildTaskPayload(form({ text: "  Hybrid beats dense. ", documentIds: [3], pipelineId: 9, title: "Hybrid?" }));
  assert.deepEqual(claim.payload, { kind: "verify_claim", title: "Hybrid?", document_ids: [3], pipeline_id: 9, claim: "Hybrid beats dense." });

  const compare = buildTaskPayload(form({ kind: "compare", documentIds: [1] }));
  assert.match(compare.errors[0], /Choose 2–4 documents/);
  const compared = buildTaskPayload(form({ kind: "compare", documentIds: [1, 2], dimensionsText: "methodology, limitations" }));
  assert.deepEqual(compared.payload.dimensions, ["methodology", "limitations"]);

  assert.deepEqual(buildTaskPayload(form({ kind: "extract" })).errors, ["Name at least one field to extract."]);
  const extract = buildTaskPayload(form({ kind: "extract", fieldsText: "samples: number" }));
  assert.deepEqual(extract.payload.fields, [{ name: "samples", type: "number" }]);

  assert.match(buildTaskPayload(form({ kind: "report", text: "x".repeat(2001) })).errors[0], /under 2000/);
});

test("evidence helpers keep citation order and put cited passages first", () => {
  const evidence = [1, 2, 3].map((id) => ({ citation_id: id, cited: id !== 2 }));
  assert.deepEqual(evidenceFor(evidence, [3, 9, 1]).map((item) => item.citation_id), [3, 1]);
  assert.deepEqual(orderedEvidence(evidence).map((item) => item.citation_id), [1, 3, 2]);
  assert.equal(citationList([2, 5]), "[2] [5]");
});

test("extracted values and statuses read naturally", () => {
  assert.equal(fieldValueText(["a", "b"]), "a; b");
  assert.equal(fieldValueText(false), "No");
  assert.equal(fieldValueText(null), "—");
  assert.equal(fieldStatusText("uncited"), "Dropped: no source cited");
});

test("the research API needs the token", () => {
  assert.equal(isProtectedApiPath("/research/tasks/"), true);
  assert.equal(isProtectedApiPath("/api/v1/research/tasks/5/export/"), true);
  assert.equal(isProtectedApiPath("/researchers/"), false);
});
