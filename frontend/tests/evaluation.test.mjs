import assert from "node:assert/strict";
import { test } from "node:test";
import { evaluationMetricEntries, formatMetricValue, metricLabel } from "../src/lib/evaluation.ts";
import { transformToAnalysisResult } from "../src/services/analysisFrames.ts";

test("only the three Ragas answer metrics are displayed, with zero and unavailable preserved", () => {
  const evaluation = {
    chunk_evaluation: { precision_k: 0.5, recall_k: 1, f1_k: 2 / 3 },
    response_evaluation: { faithfulness: 0, answer_relevancy: null, factual_correctness: 0.9, rougeL_f1: 0.7, answer_relevance: 0.8, answer_coverage: 1 },
    response_evaluation_details: { framework: "ragas" },
  };
  assert.deepEqual(evaluationMetricEntries(evaluation, "response_evaluation"), [
    ["faithfulness", 0], ["answer_relevancy", null], ["factual_correctness", 0.9],
  ]);
  assert.deepEqual(Object.fromEntries(evaluationMetricEntries(evaluation, "chunk_evaluation")), evaluation.chunk_evaluation);
  assert.equal(formatMetricValue(0), "0.0%");
  assert.equal(formatMetricValue(null), "Unavailable");
});

test("a matching metric name is insufficient to identify an earlier judge score as Ragas", () => {
  for (const framework of [undefined, "custom-judge"]) {
    const evaluation = { response_evaluation: { faithfulness: 0.95, rougeL_f1: 0.8 }, response_evaluation_details: framework ? { framework } : undefined };
    assert.deepEqual(evaluationMetricEntries(evaluation, "response_evaluation"), [
      ["faithfulness", null], ["answer_relevancy", null], ["factual_correctness", null],
    ]);
  }
});

test("retrieval result labels substitute the chosen K, independently of actual source count", () => {
  for (const k of [1, 3, 8, 20]) {
    assert.equal(metricLabel("precision_k", k), `Precision@${k}`);
    assert.equal(metricLabel("recall_k", k), `Recall@${k}`);
    assert.equal(metricLabel("f1_k", k), `F1@${k}`);
    assert.equal(metricLabel("factual_correctness", k), "Factual correctness (F1)");
  }
  for (const k of [undefined, NaN, 0, -1, 2.5]) assert.equal(metricLabel("precision_k", k), "Precision@K");
});

test("WebSocket results retain recorded K for replay and saving in browser storage", () => {
  const result = transformToAnalysisResult({ answer: "answer", method: "Dense Retrieval", top_k: 8, context: [{ chunk_id: 1, text: "One available passage" }] });
  assert.equal(result.top_k, 8);
  const reloaded = JSON.parse(JSON.stringify(result));
  assert.equal(metricLabel("precision_k", reloaded.top_k), "Precision@8");
  assert.equal(reloaded.retrievedChunks.length, 1);
});
