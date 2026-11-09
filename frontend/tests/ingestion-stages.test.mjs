import assert from "node:assert/strict";
import { test } from "node:test";
import { deriveIngestionStages, INGESTION_STAGES, isTerminalStatus, stageName, statusLabel } from "../src/features/documents/lib/ingestionStages.ts";

const states = (status, stage, options) => deriveIngestionStages(status, stage, options).map((s) => s.state);

test("QUEUED: uploaded done, everything else pending", () => {
  assert.deepEqual(states("QUEUED"), ["done", "pending", "pending", "pending", "pending", "pending"]);
});

test("UPLOADING marks the upload itself active", () => {
  assert.deepEqual(states("UPLOADING"), ["active", "pending", "pending", "pending", "pending", "pending"]);
});

test("each active stage marks earlier stages done and later ones pending", () => {
  INGESTION_STAGES.slice(1).forEach((stage, offset) => {
    const index = offset + 1;
    const expected = INGESTION_STAGES.map((_, i) => (i < index ? "done" : i === index ? "active" : "pending"));
    assert.deepEqual(states(stage.id), expected, stage.id);
  });
  const embedding = deriveIngestionStages("EMBEDDING", null, { chunkCount: 384 });
  assert.equal(embedding[3].text, "384 chunks created");
  assert.equal(embedding[4].text, "Generating embeddings…");
  assert.equal(embedding[5].text, "Index built", "pending stages show their plain label");
});

test("READY marks every stage done", () => {
  assert.deepEqual(states("READY"), Array(6).fill("done"));
});

test("FAILED marks error.stage failed and only earlier stages done", () => {
  assert.deepEqual(states("FAILED", "EMBEDDING"), ["done", "done", "done", "done", "failed", "pending"]);
  assert.deepEqual(states("FAILED", "extracting"), ["done", "failed", "pending", "pending", "pending", "pending"]);
  assert.deepEqual(states("FAILED", "UPLOADING"), ["failed", "pending", "pending", "pending", "pending", "pending"]);
  assert.equal(deriveIngestionStages("FAILED", "INDEXING")[5].text, "Indexing failed");
});

test("FAILED without a known stage keeps the upload and fails nothing else", () => {
  // e.g. job_queue_unavailable before any stage ran, or legacy not_indexed rows.
  assert.deepEqual(states("FAILED", null), ["done", "pending", "pending", "pending", "pending", "pending"]);
  assert.deepEqual(states("FAILED", "QUEUED"), ["done", "pending", "pending", "pending", "pending", "pending"]);
});

test("labels for statuses and error stages", () => {
  assert.equal(isTerminalStatus("READY"), true);
  assert.equal(isTerminalStatus("FAILED"), true);
  assert.equal(isTerminalStatus("INDEXING"), false);
  assert.equal(statusLabel("EMBEDDING"), "Embedding");
  assert.equal(stageName("EMBEDDING"), "Embedding");
  assert.equal(stageName("QUEUED"), "Queued");
  assert.equal(stageName(null), null);
});
