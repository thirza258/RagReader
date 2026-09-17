import assert from "node:assert/strict";
import { test } from "node:test";
import { analysisVariants, buildAnalysisFlow, variantKey } from "../src/lib/analysisFlow.ts";
import { formatMetricValue } from "../src/lib/evaluation.ts";

const config = { modules: [], methods: ["Dense Retrieval", "Sparse Retrieval"], models: ["provider/a", "provider/b"], top_k: 5 };
const options = {
  modules: ["adaptive_rag", "hyde", "crag", "flare", "contextual_learning"].map((id) => ({ id, label: id })),
  module_compatibility: { stages: [
    { id: "routing", modules: ["adaptive_rag"] },
    { id: "retrieval", modules: ["hyde"] },
    { id: "evidence", modules: ["crag"] },
    { id: "answer", modules: ["flare", "contextual_learning"] },
  ] },
};
const result = { method: "Dense Retrieval", aiModel: "provider/a", answer: "Answer", retrievedChunks: [] };
const trace = (enabled, steps, route = "single") => ({ enabled, steps, route, queries: [] });
const flow = (selection, evaluation, extra = {}) => buildAnalysisFlow({ ...config, modules: selection }, options, "Dense Retrieval", { ...result, evaluation, ...extra });

test("variant selection distinguishes both method and model", () => {
  assert.equal(new Set(analysisVariants(config).map((variant) => variant.key)).size, 4);
  assert.notEqual(variantKey("Dense Retrieval", "provider/a"), variantKey("Dense Retrieval", "provider/b"));
});

test("waiting results do not invent live or completed stages", () => {
  assert.ok(buildAnalysisFlow(config, options, "Dense Retrieval").every((stage) => stage.status === "planned"));
});

test("direct routes visibly skip search and evidence", () => {
  const stages = flow(["adaptive_rag", "hyde", "crag"], { module_trace: trace(["adaptive_rag", "hyde", "crag"], [{ module: "adaptive_rag", status: "completed" }, { module: "hyde", status: "skipped" }, { module: "crag", status: "skipped" }], "direct") });
  assert.equal(stages.find((stage) => stage.id === "search").status, "skipped");
  assert.equal(stages.find((stage) => stage.id === "evidence").status, "skipped");
  assert.equal(stages.find((stage) => stage.id === "answer").status, "completed");
});

test("saved enabled modules win over unsaved selection changes", () => {
  const stages = flow(["crag"], { module_trace: trace(["hyde"], [{ module: "hyde", status: "completed" }]) });
  assert.deepEqual(stages.flatMap((stage) => stage.modules.map((module) => module.id)), ["hyde"]);
});

test("a generated answer stays completed when optional answer modules were skipped", () => {
  const stages = flow(["adaptive_rag", "flare", "contextual_learning"], { module_trace: trace(["adaptive_rag", "flare", "contextual_learning"], [{ module: "adaptive_rag", status: "completed" }, { module: "flare", status: "skipped" }, { module: "contextual_learning", status: "skipped" }], "direct") });
  assert.equal(stages.find((stage) => stage.id === "answer").status, "completed");
});

test("partial module failures stay visible even after earlier success", () => {
  const stages = flow(["crag"], { module_trace: trace(["crag"], [{ module: "crag", status: "completed" }, { module: "crag", status: "fallback" }]) });
  assert.equal(stages.find((stage) => stage.id === "evidence").status, "fallback");
  assert.equal(stages.find((stage) => stage.id === "evidence").steps.length, 2);
});

test("old results and failed variants do not invent module outcomes", () => {
  assert.equal(flow(["hyde"], {})[1].status, "unrecorded");
  assert.ok(flow([], {}, { error: "failed" }).every((stage) => stage.status === "unrecorded"));
});

test("evaluation failures are shown while retaining successful stages", () => {
  const stages = flow([], { response_evaluation: { faithfulness: 0.8, answer_relevancy: null }, response_evaluation_details: { framework: "ragas", metrics: { faithfulness: { status: "completed" }, answer_relevancy: { status: "unavailable" } } } });
  assert.equal(stages.find((stage) => stage.id === "evaluate").status, "unavailable");
  assert.equal(stages.find((stage) => stage.id === "answer").status, "completed");
});

test("RRF flow explains the effective method instead of the base reranker", () => {
  const stages = buildAnalysisFlow({ ...config, modules: ["rrf_hybrid"] }, options, "Hybrid Retrieval");
  assert.match(stages.find((stage) => stage.id === "search").description, /reranker is bypassed/);
});

test("missing metric values never render as a zero score", () => {
  for (const value of [null, undefined, "", NaN, Infinity, "error 401"]) assert.equal(formatMetricValue(value), "Unavailable");
  assert.equal(formatMetricValue(0), "0.0%");
  assert.equal(formatMetricValue(0.8), "80.0%");
});

test("the flow uses the result's recorded K rather than a different configuration", () => {
  const stages = buildAnalysisFlow({ ...config, top_k: 20 }, options, "Dense Retrieval", { ...result, top_k: 8 });
  assert.match(stages.find((stage) => stage.id === "search").description, /up to 8 passages/);
  assert.doesNotMatch(stages.find((stage) => stage.id === "search").description, /20 passages/);
});

test("earlier answer scores are not treated as completed Ragas evaluation", () => {
  const stages = flow([], { chunk_evaluation: { precision_k: 1 }, response_evaluation: { faithfulness: 0.8, rougeL_f1: 0.7 } });
  assert.equal(stages.find((stage) => stage.id === "evaluate").status, "unrecorded");
  assert.match(stages.find((stage) => stage.id === "evaluate").description, /Run deep analysis again/);
});
