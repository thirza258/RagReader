import assert from "node:assert/strict";
import { test } from "node:test";
import {
  configChanges,
  describeConfig,
  diffConfigs,
  formatConfigValue,
  inactiveKeys,
  isValidModelId,
  pipelineVersionLabel,
  validateConfig,
  versionHistory,
  withStrategy,
} from "../src/features/pipelines/lib/pipelineConfig.ts";
import {
  candidateScoreColumns,
  formatCandidateScore,
  hasRankChanges,
  rankMovement,
  runPipelineLabel,
} from "../src/features/runs/lib/runMetrics.ts";
import { chunkConfigText, indexBuildText, indexVersionLabel } from "../src/features/documents/lib/indexVersions.ts";
import { formatRetrievalSummary } from "../src/features/chat/lib/retrievalSummary.ts";
import { isProtectedApiPath } from "../src/features/auth/lib/unauthorized.ts";

const DEFAULTS = {
  strategy: "dense",
  fusion: "weighted",
  hybrid_weight: 0.6,
  rrf_k: 60,
  candidate_k: 20,
  top_k: 5,
  reranker: null,
  generation_model: "openai/gpt-4o-mini",
  temperature: 0,
  prompt_version: "chat-cited-v1",
  embedding_model: "openai/text-embedding-3-small",
};

const OPTIONS = {
  strategies: ["dense", "bm25", "hybrid", "hybrid_rerank"].map((id) => ({ id, label: id })),
  fusion_methods: [{ id: "weighted", label: "Weighted" }, { id: "rrf", label: "RRF" }],
  reranker_providers: [
    { id: "ollama", label: "Ollama", open: false, models: [{ id: "nomic-embed-text", label: "Nomic" }, { id: "bge-m3", label: "BGE" }], default_model: "nomic-embed-text" },
    { id: "llm", label: "LLM", open: true, models: [{ id: "openai/gpt-4o-mini", label: "GPT-4o mini" }], default_model: "openai/gpt-4o-mini" },
  ],
  ranges: {
    candidate_k: { min: 1, max: 50 },
    top_k: { min: 1, max: 20 },
    rrf_k: { min: 1, max: 1000 },
    hybrid_weight: { min: 0, max: 1 },
    temperature: { min: 0, max: 2 },
  },
  embedding_models: ["openai/text-embedding-3-small"],
  prompt_versions: ["chat-cited-v1"],
};
const RERANKER = { provider: "ollama", model: "nomic-embed-text" };

test("the defaults validate and every range is checked like the server", () => {
  assert.deepEqual(validateConfig(DEFAULTS, OPTIONS), {});
  const errors = (patch) => validateConfig({ ...DEFAULTS, ...patch }, OPTIONS);
  assert.match(errors({ candidate_k: 0 }).candidate_k, /between 1 and 50/);
  assert.match(errors({ candidate_k: 2.5 }).candidate_k, /whole number/);
  assert.match(errors({ candidate_k: Number.NaN }).candidate_k, /whole number/);
  assert.match(errors({ top_k: 21 }).top_k, /between 1 and 20/);
  assert.match(errors({ top_k: 8, candidate_k: 5 }).top_k, /candidate top-k/);
  assert.match(errors({ temperature: 2.5 }).temperature, /between 0 and 2/);
  assert.match(errors({ generation_model: "gpt4" }).generation_model, /OpenRouter/);
  assert.match(errors({ embedding_model: "other/model" }).embedding_model, /indexed with openai\/text-embedding-3-small/);
  assert.match(errors({ strategy: "magic" }).strategy, /strategy/);
  // Fusion settings only count for hybrid strategies, and only the active one.
  assert.deepEqual(errors({ hybrid_weight: 4 }), {});
  assert.match(errors({ strategy: "hybrid", hybrid_weight: 1.5 }).hybrid_weight, /between 0 and 1/);
  assert.deepEqual(errors({ strategy: "hybrid", fusion: "rrf", hybrid_weight: 1.5 }), {});
  assert.match(errors({ strategy: "hybrid", fusion: "rrf", rrf_k: 0 }).rrf_k, /between 1 and 1000/);
});

test("a reranker exists exactly for hybrid + reranking", () => {
  assert.match(validateConfig({ ...DEFAULTS, reranker: RERANKER }, OPTIONS).reranker, /Only hybrid \+ reranking/);
  assert.match(validateConfig({ ...DEFAULTS, strategy: "hybrid_rerank" }, OPTIONS).reranker, /Choose a reranker/);
  assert.deepEqual(validateConfig({ ...DEFAULTS, strategy: "hybrid_rerank", reranker: RERANKER }, OPTIONS), {});
  assert.match(validateConfig({ ...DEFAULTS, strategy: "hybrid_rerank", reranker: { provider: "ollama", model: "llama" } }, OPTIONS).reranker, /listed models/);
  assert.deepEqual(validateConfig({ ...DEFAULTS, strategy: "hybrid_rerank", reranker: { provider: "llm", model: "vendor/any-model" } }, OPTIONS), {});
  assert.match(validateConfig({ ...DEFAULTS, strategy: "hybrid_rerank", reranker: { provider: "llm", model: "no slash" } }, OPTIONS).reranker, /OpenRouter/);

  const rerank = withStrategy(DEFAULTS, "hybrid_rerank", RERANKER);
  assert.deepEqual(rerank.reranker, RERANKER);
  assert.notEqual(rerank.reranker, RERANKER); // a copy, not the shared default
  assert.equal(withStrategy(rerank, "hybrid", RERANKER).reranker, null);
  const kept = withStrategy({ ...rerank, reranker: { provider: "llm", model: "a/b" } }, "hybrid_rerank", RERANKER);
  assert.deepEqual(kept.reranker, { provider: "llm", model: "a/b" });
});

test("the form hides settings the strategy does not use", () => {
  assert.deepEqual([...inactiveKeys({ strategy: "dense", fusion: "weighted" })].sort(), ["fusion", "hybrid_weight", "reranker", "rrf_k"]);
  assert.deepEqual([...inactiveKeys({ strategy: "hybrid", fusion: "weighted" })].sort(), ["reranker", "rrf_k"]);
  assert.deepEqual([...inactiveKeys({ strategy: "hybrid_rerank", fusion: "rrf" })].sort(), ["hybrid_weight"]);
});

test("an edit sends only what changed", () => {
  assert.deepEqual(configChanges(DEFAULTS, DEFAULTS), {});
  assert.deepEqual(configChanges(DEFAULTS, { ...DEFAULTS, top_k: 3, strategy: "hybrid" }), { strategy: "hybrid", top_k: 3 });
  assert.deepEqual(configChanges({ ...DEFAULTS, reranker: RERANKER }, { ...DEFAULTS, reranker: { ...RERANKER } }), {});
});

test("versions read as diffs against the version before them", () => {
  const v1 = { id: 11, pipeline_id: 3, number: 1, config: DEFAULTS, config_hash: "a", created_at: "2026-11-01T10:00:00Z" };
  const v2 = { ...v1, id: 12, number: 2, config: { ...DEFAULTS, strategy: "hybrid_rerank", reranker: RERANKER, top_k: 3 }, config_hash: "b" };
  const v3 = { ...v1, id: 13, number: 3, config: { ...v2.config, temperature: 0.2, hybrid_weight: 0.75 }, config_hash: "c" };
  const history = versionHistory([v1, v3, v2]);
  assert.deepEqual(history.map((entry) => entry.version.number), [3, 2, 1]);
  assert.deepEqual(history[2], { version: v1, changes: [], initial: true });
  assert.deepEqual(history[1].changes, [
    { key: "strategy", label: "Retrieval", from: "Dense", to: "Hybrid + reranking" },
    { key: "top_k", label: "Final top-k", from: "5", to: "3" },
    { key: "reranker", label: "Reranker", from: "none", to: "ollama · nomic-embed-text" },
  ]);
  assert.deepEqual(history[0].changes.map((change) => [change.key, change.from, change.to]), [
    ["hybrid_weight", "0.6", "0.75"],
    ["temperature", "0", "0.2"],
  ]);
  assert.deepEqual(diffConfigs(null, DEFAULTS), []);
});

test("configurations and versions read as one line", () => {
  assert.equal(describeConfig(DEFAULTS), "Dense · 20 → 5 · openai/gpt-4o-mini, temperature 0");
  assert.equal(
    describeConfig({ ...DEFAULTS, strategy: "hybrid_rerank", reranker: RERANKER, temperature: 0.2 }),
    "Hybrid + reranking · weighted 0.6 · 20 → 5 · reranker ollama · nomic-embed-text · openai/gpt-4o-mini, temperature 0.2",
  );
  assert.equal(describeConfig({ ...DEFAULTS, strategy: "hybrid", fusion: "rrf", rrf_k: 30 }), "Hybrid (dense + BM25) · RRF k 30 · 20 → 5 · openai/gpt-4o-mini, temperature 0");
  assert.equal(describeConfig(null), "—");
  assert.equal(formatConfigValue("hybrid_weight", 0.123456), "0.1235");
  assert.equal(formatConfigValue("fusion", "rrf"), "Reciprocal rank fusion");
  assert.equal(pipelineVersionLabel({ id: 4, pipeline_id: 2, name: "Default (dense)", number: 2 }), "Default (dense) v2");
  assert.equal(pipelineVersionLabel({ name: "Mine", version: 3 }), "Mine v3");
  assert.equal(pipelineVersionLabel(null), null);
  assert.equal(runPipelineLabel({ pipeline: { id: 1, name: "Mine", version: 2, version_id: 9 } }), "Mine v2");
  assert.equal(runPipelineLabel({ pipeline: null }), null);
  assert.equal(isValidModelId("openai/gpt-4o-mini-2024-07-18"), true);
  assert.equal(isValidModelId("vendor/model:free"), true);
  assert.equal(isValidModelId("/model"), false);
});

test("candidate scores keep enough digits for each kind of score", () => {
  assert.equal(formatCandidateScore(0.8234), "0.823");
  assert.equal(formatCandidateScore(1 / 61), "0.0164");
  assert.equal(formatCandidateScore(12.3456), "12.35");
  assert.equal(formatCandidateScore(123.45), "123.5");
  assert.equal(formatCandidateScore(-0.05), "-0.0500");
  assert.equal(formatCandidateScore(0), "0");
  assert.equal(formatCandidateScore(null), "—");
  assert.equal(formatCandidateScore(Number.NaN), "—");
});

test("rank movement and the columns a candidate table needs", () => {
  assert.deepEqual(rankMovement({ rank: 1, retrieval_rank: 4 }), { before: 4, after: 1, delta: 3, text: "4 → 1 (up 3)" });
  assert.deepEqual(rankMovement({ rank: 3, retrieval_rank: 1 }), { before: 1, after: 3, delta: -2, text: "1 → 3 (down 2)" });
  assert.equal(rankMovement({ rank: 2, retrieval_rank: 2 }).text, "2");
  assert.equal(rankMovement({ rank: 2 }).text, "2");
  assert.equal(hasRankChanges([{ rank: 1, retrieval_rank: 1 }, { rank: 2, retrieval_rank: 2 }]), false);
  assert.equal(hasRankChanges([{ rank: 1, retrieval_rank: 2 }, { rank: 2, retrieval_rank: 1 }]), true);

  const base = { retrieval_score: 0.5, dense_score: null, bm25_score: null, fused_score: null, rerank_score: null };
  // Phase 2 runs only have the retrieval score.
  assert.deepEqual(candidateScoreColumns([{ ...base, dense_score: undefined }]).map((column) => column.key), ["retrieval_score"]);
  assert.deepEqual(candidateScoreColumns([{ ...base, rerank_score: 0.9 }]).map((column) => column.key), ["retrieval_score", "rerank_score"]);
  assert.deepEqual(candidateScoreColumns([{ ...base, dense_score: 0.5 }]).map((column) => column.key), ["dense_score"]);
  assert.deepEqual(candidateScoreColumns([{ ...base, bm25_score: 3.1 }]).map((column) => column.key), ["bm25_score"]);
  assert.deepEqual(
    candidateScoreColumns([{ ...base, dense_score: 0.5, bm25_score: 0, fused_score: 0.03, rerank_score: 0.8 }]).map((column) => column.label),
    ["Dense", "BM25", "Fused", "Rerank"],
  );
});

test("index versions read with their build settings", () => {
  const current = { id: 7, method: "dense", status: "ready", is_current: true, embedding_model: "openai/text-embedding-3-small", chunk_config: { strategy: "fixed", chunk_size: 512, overlap: 50 }, chunk_count: 1384 };
  assert.equal(indexVersionLabel(current), "Index #7 · dense · current");
  assert.equal(indexBuildText(current), "openai/text-embedding-3-small · fixed, 512 characters, 50 overlap · 1,384 chunks");
  const older = { ...current, id: 5, is_current: false, embedding_model: null, chunk_config: null, chunk_count: null };
  assert.equal(indexVersionLabel(older), "Index #5 · dense · superseded");
  assert.equal(indexBuildText(older), "Build settings are recorded for the current index only.");
  assert.equal(indexVersionLabel({ ...older, status: "failed" }), "Index #5 · dense · failed · superseded");
  assert.equal(chunkConfigText(null), null);
  assert.equal(chunkConfigText({ strategy: "paragraph" }), "paragraph");
});

test("the footer marks a reranked context and pipeline paths need the token", () => {
  const retrieval = { candidate_count: 20, context_count: 5, cited_count: 3, rerank: { applied: true } };
  assert.equal(formatRetrievalSummary(retrieval), "Retrieval: 20 → reranked 5 → 3 cited");
  assert.equal(formatRetrievalSummary({ ...retrieval, rerank: { applied: false, fallback: true } }), "Retrieval: 20 → 5 → 3 cited");
  for (const path of ["/pipelines/", "/pipelines/options/", "/api/v1/pipelines/3/versions/", "/indexes/?document_id=4", "/indexes/7/"]) {
    assert.equal(isProtectedApiPath(path), true, path);
  }
});
