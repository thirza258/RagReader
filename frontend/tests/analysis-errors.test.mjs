import assert from "node:assert/strict";
import { test } from "node:test";
import { processRawFrame, transformToAnalysisResult } from "../src/services/analysisFrames.ts";
import { analysisRequestId, analysisFailureSummary } from "../src/lib/analysisRequest.ts";

test("fatal job errors reach the UI before closing and never create result cards", () => {
  const calls = [];
  processRawFrame(JSON.stringify({ batch_id: "batch", status: "ERROR", terminal: true, error: "Job ID must be a valid UUID.", error_code: "invalid_job_id", retryable: false }), {
    batchId: "batch", onResult: () => calls.push("result"),
    onServerError: (message) => calls.push(message.error_code),
  }, () => calls.push("closed"));
  assert.deepEqual(calls, ["invalid_job_id", "closed"]);
});

test("waiting for the owner is a notice and does not finish the batch", () => {
  const calls = [];
  processRawFrame(JSON.stringify({ status: "WAITING", message: "This batch is already running." }), {
    onResult: () => calls.push("result"), onServerError: () => calls.push("error"),
    onWaiting: (message) => calls.push(message),
  }, () => calls.push("closed"));
  assert.deepEqual(calls, ["This batch is already running."]);
});

test("failed variants retain their provider code and retry guidance", () => {
  const result = transformToAnalysisResult({ batch_id: "batch", method: "Dense Retrieval", aiModel: "provider/model", error: "Embedding timed out", error_code: "provider_timeout", retryable: true });
  assert.equal(result.error, "Embedding timed out");
  assert.equal(result.error_code, "provider_timeout");
  assert.equal(result.retryable, true);
  assert.deepEqual(result.retrievedChunks, []);
});

test("frames from a different batch cannot close or overwrite the active run", () => {
  const calls = [];
  const options = { batchId: "current", onResult: () => calls.push("result"), onServerError: () => calls.push("error"), onWaiting: () => calls.push("waiting") };
  for (const frame of [{ status: "COMPLETE" }, { status: "ERROR", error: "old error" }, { status: "WAITING" }, { answer: "old answer", method: "Dense Retrieval" }]) {
    processRawFrame(JSON.stringify({ ...frame, batch_id: "old" }), options, () => calls.push("closed"));
  }
  assert.deepEqual(calls, []);
});

test("request identity survives remounts and changes only for a new intent or conversation", () => {
  const first = analysisRequestId("conversation");
  assert.match(first, /^[\da-f-]{36}$/);
  assert.equal(analysisRequestId("conversation"), first);
  assert.notEqual(analysisRequestId("different-conversation"), first);
  const rerun = analysisRequestId("conversation", "run_1");
  assert.notEqual(rerun, first);
  assert.equal(analysisRequestId("conversation", "run_1"), rerun);
  assert.notEqual(analysisRequestId("conversation", "run_2"), rerun);
});

test("partial failure is described without claiming successful completion", () => {
  assert.equal(analysisFailureSummary(0, 9), "");
  assert.match(analysisFailureSummary(2, 9), /^2 of 9 variants failed/);
});
