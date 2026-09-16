import assert from "node:assert/strict";
import { test } from "node:test";
import { buildAnalysisFlow, variantKey } from "../src/lib/analysisFlow.ts";
import { interruptLiveProgress, isAnalysisProgressMessage, updateLiveProgress } from "../src/lib/liveAnalysis.ts";
import { processRawFrame, transformToAnalysisResult } from "../src/services/analysisFrames.ts";

const key = variantKey("Dense Retrieval", "provider/a");
const config = { modules: ["hyde"], methods: ["Dense Retrieval"], models: ["provider/a"], top_k: 5 };
const options = { modules: [{ id: "hyde", label: "HyDE", stage: "Query" }] };
function frame(sequence, event = {}, extra = {}) {
  return { status: "STAGE_PROGRESS", batch_id: "batch", method: "Dense Retrieval", aiModel: "provider/a", attempt_id: "attempt", sequence, event: { kind: "stage", id: "search", status: "running", detail: "Searching", ...event }, ...extra };
}
const apply = (previous, message) => updateLiveProgress(previous, message, "batch");

test("live frames update the correct method and model without creating results", () => {
  const received = [];
  const results = [];
  const percentages = [];
  processRawFrame(JSON.stringify(frame(1)), { onStageProgress: (message) => received.push(message), onResult: (result) => results.push(result), onProgress: (...args) => percentages.push(args) });
  assert.equal(received.length, 1);
  assert.equal(results.length, 0);
  assert.equal(percentages.length, 0);
  assert.equal(transformToAnalysisResult({ ...frame(1), answer: "Must never become a result" }), null);
  let state = apply({}, received[0]);
  state = apply(state, frame(1, { id: "answer" }, { aiModel: "provider/b" }));
  assert.equal(state[key].stages.search.status, "running");
  assert.equal(state[variantKey("Dense Retrieval", "provider/b")].stages.answer.status, "running");
});

test("mixed newline frames preserve event, result and completion ordering", () => {
  const calls = [];
  const result = { method: "Dense Retrieval", aiModel: "provider/a", answer: "Done", progress: 100 };
  processRawFrame([frame(1), result, { status: "COMPLETE" }].map(JSON.stringify).join("\n"), { onStageProgress: () => calls.push("live"), onResult: () => calls.push("result") }, () => calls.push("complete"));
  assert.deepEqual(calls, ["live", "result", "complete"]);
});

test("malformed and cross-batch events cannot alter an active run", () => {
  const state = apply({}, frame(1));
  for (const message of [frame(2, {}, { batch_id: "old" }), frame(2, { status: "fictional" }), frame(2, { queries: "wrong" }), frame(2, { score: Infinity }), frame(2, { id: "nonexistent-stage" })]) {
    assert.equal(apply(state, message), state);
  }
  assert.equal(isAnalysisProgressMessage(null), false);
  assert.equal(isAnalysisProgressMessage({ status: "STAGE_PROGRESS" }), false);
});

test("duplicate and out-of-order events do not move a stage backwards", () => {
  const state = apply({}, frame(3, { status: "completed" }));
  assert.equal(apply(state, frame(3)), state);
  assert.equal(apply(state, frame(2)), state);
});

test("a new attempt replaces old partial stages and rejects late old events", () => {
  let state = apply({}, frame(3, { status: "completed" }));
  state = apply(state, frame(1, { id: "question" }, { attempt_id: "retry" }));
  assert.equal(state[key].stages.search, undefined);
  assert.equal(state[key].stages.question.status, "running");
  assert.equal(apply(state, frame(1)), state);
  assert.equal(apply(state, frame(4)), state);
});

test("actual live stages are shown while future stages stay planned", () => {
  let state = apply({}, frame(1, { id: "question", status: "completed" }));
  state = apply(state, frame(2));
  state = apply(state, frame(3, { kind: "module", id: "hyde", label: "HyDE", detail: "Preparing hypothesis" }));
  const stages = buildAnalysisFlow(config, options, "Dense Retrieval", undefined, state[key]);
  assert.deepEqual(stages.map((stage) => stage.status), ["completed", "running", "planned", "planned", "planned"]);
  assert.equal(stages[1].steps[0].status, "running");
});

test("interruption pauses active steps and modules while retaining completed steps", () => {
  let state = apply({}, frame(1, { id: "question", status: "completed" }));
  state = apply(state, frame(2));
  state = apply(state, frame(3, { kind: "module", id: "hyde" }));
  state = interruptLiveProgress(state);
  const stages = buildAnalysisFlow(config, options, "Dense Retrieval", undefined, state[key]);
  assert.equal(stages[0].status, "completed");
  assert.equal(stages[1].status, "paused");
  assert.equal(stages[1].steps[0].status, "paused");
  assert.equal(apply(state, frame(4, { id: "search", status: "completed" }))[key].interrupted, false);
});

test("Stop immediately pauses live stages even before socket callbacks", () => {
  const state = apply({}, frame(1));
  assert.equal(buildAnalysisFlow(config, options, "Dense Retrieval", undefined, state[key], false)[1].status, "paused");
});

test("direct routes show real skips before the answer has finished", () => {
  let state = apply({}, frame(1, { kind: "route", id: "direct", status: "completed" }));
  state = apply(state, frame(2, { status: "skipped" }));
  state = apply(state, frame(3, { id: "evidence", status: "skipped" }));
  state = apply(state, frame(4, { id: "answer" }));
  const stages = buildAnalysisFlow(config, options, "Dense Retrieval", undefined, state[key]);
  assert.deepEqual(stages.slice(1, 4).map((stage) => stage.status), ["skipped", "skipped", "running"]);
  assert.match(stages[1].description, /direct answer/);
});

test("module fallback and metric failure preserve the remaining running work", () => {
  let state = apply({}, frame(1));
  state = apply(state, frame(2, { kind: "module", id: "hyde", status: "fallback" }));
  assert.equal(buildAnalysisFlow(config, options, "Dense Retrieval", undefined, state[key])[1].status, "running");
  state = apply(state, frame(3, { status: "completed" }));
  assert.equal(buildAnalysisFlow(config, options, "Dense Retrieval", undefined, state[key])[1].status, "fallback");
  state = apply(state, frame(4, { id: "evaluate" }));
  state = apply(state, frame(5, { kind: "metric", id: "faithfulness", status: "completed", score: 0 }));
  state = apply(state, frame(6, { kind: "metric", id: "answer_relevancy", status: "unavailable", score: null }));
  assert.equal(state[key].metrics.faithfulness.score, 0);
  assert.equal(state[key].metrics.answer_relevancy.score, null);
  assert.equal(buildAnalysisFlow(config, options, "Dense Retrieval", undefined, state[key])[4].status, "running");
  state = apply(state, frame(7, { id: "evaluate", status: "completed" }));
  assert.equal(buildAnalysisFlow(config, options, "Dense Retrieval", undefined, state[key])[4].status, "unavailable");
});

test("failed variants retain observed outcomes and successful saved results replace live state", () => {
  let state = apply({}, frame(1, { status: "completed" }));
  state = apply(state, frame(2, { id: "answer", status: "failed" }));
  const saved = { method: "Dense Retrieval", aiModel: "provider/a", evaluation: {}, error: "failure" };
  const stages = buildAnalysisFlow(config, options, "Dense Retrieval", saved, state[key]);
  assert.equal(stages[1].status, "completed");
  assert.equal(stages[3].status, "failed");
  assert.equal(buildAnalysisFlow({ ...config, modules: [] }, options, "Dense Retrieval", { ...saved, error: undefined }, state[key])[3].status, "completed");
});

test("follow-up searches retain their actual phase and deduplicate used questions", () => {
  let state = apply({}, frame(1, { kind: "module", id: "rag_fusion", queries: ["proposed only"] }));
  state = apply(state, frame(2, { kind: "activity", id: "retrieval", stage: "answer", queries: ["follow-up"] }));
  state = apply(state, frame(3, { kind: "activity", id: "retrieval", stage: "answer", queries: ["follow-up"] }));
  assert.deepEqual(state[key].queries, ["follow-up"]);
  assert.equal(state[key].activity.stage, "answer");
});
