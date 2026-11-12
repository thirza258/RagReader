import assert from "node:assert/strict";
import { test } from "node:test";
import { flattenSpans, layoutWaterfall } from "../src/features/runs/lib/waterfall.ts";
import {
  candidateToEvidence,
  describeRewrite,
  formatCount,
  formatMs,
  formatPercentiles,
  formatRate,
  funnelShort,
  funnelText,
  runFunnel,
  runIdOf,
  runLine,
  stageName,
  summaryCards,
} from "../src/features/runs/lib/runMetrics.ts";
import { isWorkspaceApiPath } from "../src/features/auth/lib/unauthorized.ts";

const span = (name, start_ms, duration_ms, children = [], extra = {}) => ({ name, label: name.toUpperCase(), status: "completed", start_ms, duration_ms, detail: "", error_code: null, data: {}, children, ...extra });

test("waterfall rows follow the tree, nest by depth and scale to the total", () => {
  const tree = [
    span("chat.turn", 0, 1000, [
      span("retrieve", 100, 200, [span("retrieve.search", 150, 50)]),
      span("rewrite", 0, 100),
      span("generate", 300, 600, [span("generate.first_token", 300, 150)]),
    ]),
  ];
  const { scaleMs, rows } = layoutWaterfall(tree, { totalMs: 1000 });
  assert.equal(scaleMs, 1000);
  assert.deepEqual(rows.map((row) => [row.name, row.depth]), [
    ["chat.turn", 0],
    ["rewrite", 1],
    ["retrieve", 1],
    ["retrieve.search", 2],
    ["generate", 1],
    ["generate.first_token", 2],
  ]);
  const byName = Object.fromEntries(rows.map((row) => [row.name, row]));
  assert.deepEqual([byName["chat.turn"].offsetPct, byName["chat.turn"].widthPct], [0, 100]);
  assert.deepEqual([byName.retrieve.offsetPct, byName.retrieve.widthPct], [10, 20]);
  assert.deepEqual([byName["retrieve.search"].offsetPct, byName["retrieve.search"].widthPct], [15, 5]);
  assert.deepEqual([byName.generate.offsetPct, byName.generate.widthPct, byName.generate.endMs], [30, 60, 900]);
  assert.equal(byName.rewrite.label, "REWRITE");
});

test("the scale grows to the latest span end when spans outlast the total", () => {
  const { scaleMs, rows } = layoutWaterfall([span("root", 0, 1250, [span("persist", 1000, 250)])], { totalMs: 1000 });
  assert.equal(scaleMs, 1250);
  const persist = rows[1];
  assert.deepEqual([persist.offsetPct, persist.widthPct], [80, 20]);
  assert.ok(rows.every((row) => row.offsetPct + row.widthPct <= 100));
});

test("tiny, missing and malformed timings stay drawable and inside the track", () => {
  const { rows } = layoutWaterfall(
    [span("root", 0, 1000, [span("fast", 400, 0.2), span("unclosed", 500, null), span("weird", -5, Number.NaN), span("last", 1000, 0)])],
    { minWidthPct: 0.5 },
  );
  const byName = Object.fromEntries(rows.map((row) => [row.name, row]));
  assert.equal(byName.fast.widthPct, 0.5);
  assert.deepEqual([byName.unclosed.durationMs, byName.unclosed.widthPct], [0, 0.5]);
  assert.deepEqual([byName.weird.startMs, byName.weird.offsetPct], [0, 0]);
  assert.deepEqual([byName.last.offsetPct, byName.last.widthPct], [99.5, 0.5]);
  assert.deepEqual(rows.map((row) => row.name), ["root", "weird", "fast", "unclosed", "last"]); // children by start
});

test("an empty or zero-length trace lays out without dividing by zero", () => {
  assert.deepEqual(layoutWaterfall([]), { scaleMs: 0, rows: [] });
  assert.deepEqual(layoutWaterfall(null, { totalMs: 50 }), { scaleMs: 50, rows: [] });
  const { rows } = layoutWaterfall([span("root", 0, 0)]);
  assert.deepEqual([rows[0].offsetPct, rows[0].widthPct], [0, 0.5]);
  assert.deepEqual(flattenSpans([span("a", 0, 1, [span("b", 0, 1)])]).map((item) => item.key), ["0", "0.0"]);
});

test("latencies, percentiles, rates and counts are formatted for people", () => {
  assert.equal(formatMs(null), "—");
  assert.equal(formatMs(-3), "—");
  assert.equal(formatMs(0.3), "<1 ms");
  assert.equal(formatMs(120.4), "120 ms");
  assert.equal(formatMs(2450), "2.45 s");
  assert.equal(formatMs(12345), "12.3 s");
  assert.equal(formatPercentiles({ p50: 300, p95: 880, count: 5 }), "p50 300 ms · p95 880 ms");
  assert.equal(formatPercentiles({ p50: 2400, p95: 5100, count: 9 }), "p50 2.40 s · p95 5.10 s");
  assert.equal(formatPercentiles({ p50: null, p95: null, count: 0 }), "—");
  assert.equal(formatRate(0.375), "37.5%");
  assert.equal(formatRate(0), "0%");
  assert.equal(formatRate(1), "100%");
  assert.equal(formatRate(0.33333), "33.3%");
  assert.equal(formatRate(null), "—");
  assert.equal(formatCount(12345), "12,345");
  assert.equal(stageName("retrieve"), "retrieval");
  assert.equal(stageName("generate"), "generation");
  assert.equal(stageName(null), "an unknown step");
});

test("the funnel reads candidates, context and cited from runs and Phase 1 metadata", () => {
  const steps = runFunnel({ candidate_count: 20, context_count: 5, cited_count: 3 });
  assert.equal(funnelText(steps), "Retrieved candidates 20 → Context 5 → Cited 3");
  assert.equal(funnelShort(steps), "20 → 5 → 3");
  assert.equal(funnelText(runFunnel({ candidate_count: 4 })), "Retrieved candidates 4 → Context — → Cited —");
  assert.equal(funnelShort(runFunnel(null)), "— → — → —");
});

test("the rewrite explains itself when it did not happen", () => {
  assert.deepEqual(describeRewrite({ original: "q", rewritten: "better q", rewrite_applied: true, rewrite_reason: "rewritten" }), { applied: true, text: "better q" });
  assert.match(describeRewrite({ rewrite_applied: false, rewrite_reason: "first_question" }).text, /^Not rewritten: first question/);
  assert.match(describeRewrite({ rewrite_applied: false, rewrite_reason: "failed" }).text, /request failed/);
  assert.match(describeRewrite({ rewrite_applied: false, rewrite_reason: "unusable" }).text, /unusable/);
  assert.equal(describeRewrite({ rewrite_applied: false, rewrite_reason: null }).text, "Not rewritten.");
  assert.equal(describeRewrite(null).applied, false);
});

const SUMMARY = {
  workspace_id: 3, days: 30, source: null, since: "",
  runs: { total: 8, completed: 5, failed: 3 },
  failure_rate: 0.375,
  failures_by_stage: { retrieval: { count: 1, rate: 0.125 }, generation: { count: 1, rate: 0.125 }, other: { count: 1, rate: 0.125 } },
  latency_ms: {
    sample_size: 5,
    total: { p50: 300, p95: 880, count: 5 },
    retrieval: { p50: 25, p95: 38.5, count: 4 },
    generation: { p50: 250, p95: 786, count: 5 },
    first_token: { p50: 120, p95: 440, count: 5 },
  },
  tokens: { prompt: 960, completion: 40, total: 1000, runs_with_usage: 4, average_per_run: 250 },
  ingestion: { documents: 5, ready: 2, failed: 1, in_progress: 1, not_indexed: 1, success_rate: 0.6667, failure_rate: 0.3333, attempts: { total: 4, succeeded: 2, failed: 1, failure_rate: 0.3333 } },
};

test("summary cards derive the §49 numbers", () => {
  const cards = Object.fromEntries(summaryCards(SUMMARY).map((card) => [card.key, card]));
  assert.deepEqual(Object.keys(cards), ["runs", "failures", "total", "first_token", "retrieval", "generation", "tokens", "ingestion"]);
  assert.deepEqual([cards.runs.value, cards.runs.detail], ["8", "5 completed · 3 failed"]);
  assert.deepEqual([cards.failures.value, cards.failures.detail], ["37.5%", "retrieval 12.5% · generation 12.5%"]);
  assert.equal(cards.total.value, "p50 300 ms · p95 880 ms");
  assert.equal(cards.retrieval.value, "p50 25 ms · p95 39 ms");
  assert.equal(cards.tokens.value, "250");
  assert.deepEqual([cards.ingestion.value, cards.ingestion.detail], ["66.7%", "2 ready · 1 failed · 1 in progress"]);
  assert.deepEqual(summaryCards(null), []);
  const empty = summaryCards({
    ...SUMMARY,
    runs: { total: 0, completed: 0, failed: 0 },
    failure_rate: null,
    latency_ms: { ...SUMMARY.latency_ms, total: { p50: null, p95: null, count: 0 } },
    tokens: { ...SUMMARY.tokens, average_per_run: null },
  });
  assert.deepEqual(empty.filter((card) => ["failures", "total", "tokens"].includes(card.key)).map((card) => card.value), ["—", "—", "—"]);
});

const candidate = (extra = {}) => ({
  rank: 7, document_id: 12, document_title: "Paper", document_available: true, index_version_id: 3, chunk_id: 99,
  page_number: 4, page_end: 4, char_start: 10, char_end: 50, text: "passage", retrieval_score: 0.5, rerank_score: null,
  selected_for_context: false, cited: false, citation_id: null, ...extra,
});

test("a candidate opens in the reader like a citation", () => {
  const evidence = candidateToEvidence(candidate());
  assert.equal(evidence.citation_id, 0);
  assert.equal(evidence.candidate_rank, 7);
  assert.deepEqual([evidence.document_id, evidence.char_start, evidence.char_end, evidence.page_number], [12, 10, 50, 4]);
  assert.equal(candidateToEvidence(candidate({ citation_id: 2, selected_for_context: true })).citation_id, 2);
  assert.equal(candidateToEvidence(candidate({ document_id: null, document_available: false })), null);
});

test("run ids and list lines come from the stored shapes", () => {
  assert.equal(runIdOf({ retrieval: { run_id: 41 } }), 41);
  assert.equal(runIdOf({ retrieval: {} }), null);
  assert.equal(runIdOf({ retrieval: null }), null);
  assert.equal(runIdOf({ retrieval: { run_id: "41" } }), null);
  const run = { latency_ms: { total: 2450, first_token: 900 }, token_usage: { total_tokens: 908 }, candidate_count: 20, context_count: 5, cited_count: 3 };
  assert.equal(runLine(run), "2.45 s · first token 900 ms · 908 tokens · 20 → 5 → 3");
  assert.equal(runLine({ ...run, latency_ms: { total: 5, first_token: null }, token_usage: null }), "5 ms · 20 → 5 → 3");
});

test("the runs endpoints count as the token-protected API", () => {
  assert.equal(isWorkspaceApiPath("/retrieval/runs/"), true);
  assert.equal(isWorkspaceApiPath("/api/v1/retrieval/runs/41/"), true);
  assert.equal(isWorkspaceApiPath("/conversations/9/messages/"), true);
  assert.equal(isWorkspaceApiPath("/start-analysis/"), false);
});
