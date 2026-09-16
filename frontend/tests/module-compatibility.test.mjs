import assert from "node:assert/strict";
import { test } from "node:test";
import { activeCompatibilityRules } from "../src/lib/moduleCompatibility.ts";

const rules = [
  { id: "pair", modules: ["crag", "self_route"], min_selected: 2 },
  { id: "routing", modules: ["adaptive_rag"], min_selected: 1 },
  { id: "cost", modules: ["hyde", "rag_fusion", "memo_rag"], min_selected: 2 },
  { id: "sparse", modules: ["hyde", "raptor"], min_selected: 1, methods: ["Sparse Retrieval"] },
];

test("pair notes appear only when both modules are selected", () => {
  assert.deepEqual(activeCompatibilityRules(rules, ["crag"], []), []);
  assert.deepEqual(activeCompatibilityRules(rules, ["crag", "self_route"], []).map(r => r.id), ["pair"]);
});

test("turning modules off removes stale notes", () => {
  assert.deepEqual(activeCompatibilityRules(rules, [], ["Sparse Retrieval"]), []);
});

test("embedding requirements follow the selected retrieval methods", () => {
  assert.deepEqual(activeCompatibilityRules(rules, ["hyde"], ["Dense Retrieval"]), []);
  assert.deepEqual(activeCompatibilityRules(rules, ["hyde"], ["Sparse Retrieval"]).map(r => r.id), ["sparse"]);
});

test("multiple query modules activate cost notes without counting duplicate selections", () => {
  assert.deepEqual(activeCompatibilityRules(rules, ["hyde", "hyde"], []), []);
  assert.deepEqual(activeCompatibilityRules(rules, ["memo_rag", "rag_fusion"], []).map(r => r.id), ["cost"]);
});

test("all selected modules retain applicable notes including conditional routing", () => {
  const selection = [...new Set(rules.flatMap(rule => rule.modules))];
  assert.deepEqual(activeCompatibilityRules(rules, selection, ["Sparse Retrieval"]).map(r => r.id), rules.map(r => r.id));
});
