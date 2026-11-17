import assert from "node:assert/strict";
import { test } from "node:test";
import {
  formatAggregate,
  formatMetric,
  itemMetricText,
  metricDefinition,
  metricKeysFor,
  metricLabel,
  parseMetricKey,
  reasonText,
  sortMetricKeys,
  topReason,
} from "../src/features/evaluation/lib/metrics.ts";
import {
  ciExcludesZero,
  ciText,
  compareIdsParam,
  comparisonTradeOffs,
  configValueText,
  deltaTone,
  formatCi,
  formatOperational,
  formatOperationalDelta,
  formatSigned,
  operationalLabel,
  significance,
  tradeOff,
  winLossText,
} from "../src/features/evaluation/lib/comparison.ts";
import {
  FAILURE_CODES,
  failureCountRows,
  failureFilterOptions,
  failureFilterQuery,
  failureLabel,
  groupLabels,
} from "../src/features/evaluation/lib/failures.ts";
import {
  describeSource,
  detectFormat,
  formatCompactSources,
  parseCompactSources,
  parseCsvRows,
  parseDatasetCsv,
  parseDatasetFile,
  parseDatasetJson,
  toCsv,
  validateItemInput,
} from "../src/features/evaluation/lib/datasetCsv.ts";
import { evidenceToExpected, fromSourceDraft, tagsFromText, toSourceDraft } from "../src/features/evaluation/lib/itemForm.ts";
import {
  MAX_COMPARE,
  experimentActions,
  headlineMetrics,
  isActive,
  parseKValues,
  parseSeed,
  progressFraction,
  progressText,
  sameDataset,
  statusLabel,
  toggleCompare,
  warningTitle,
} from "../src/features/evaluation/lib/experiments.ts";
import { isProtectedApiPath } from "../src/features/auth/lib/unauthorized.ts";

const MINUS = "−";

function source(overrides = {}) {
  return { document_id: 12, chunk_id: null, index_version_id: null, char_start: null, char_end: null, page: null, page_end: null, text: "", ...overrides };
}

// ── Metrics ─────────────────────────────────────────────────────────────────

test("metric keys parse into a base and an optional K, and labels substitute K", () => {
  assert.deepEqual(parseMetricKey("recall@5"), { base: "recall", k: 5 });
  assert.deepEqual(parseMetricKey("ndcg@10"), { base: "ndcg", k: 10 });
  assert.deepEqual(parseMetricKey("mrr"), { base: "mrr", k: null });
  assert.equal(metricLabel("recall@5"), "Recall@5");
  assert.equal(metricLabel("hit_rate@3"), "Hit rate@3");
  assert.equal(metricLabel("ndcg@10"), "nDCG@10");
  assert.equal(metricLabel("context_precision"), "Context precision");
  assert.equal(metricLabel("citation_completeness"), "Citation completeness");

  const precision = metricDefinition("precision@5");
  assert.equal(precision.group, "retrieval");
  assert.match(precision.definition, /divided by 5, also when fewer than 5 passages/);
  assert.equal(metricDefinition("faithfulness").group, "generation");
  assert.equal(metricDefinition("answer_correctness").group, "generation");
  assert.equal(metricDefinition("mrr").higherIsBetter, true);
  // A key the client does not know keeps its name; an at-K base without K is unknown too.
  assert.deepEqual([metricDefinition("bleu").label, metricDefinition("bleu").known], ["bleu", false]);
  assert.equal(metricDefinition("recall").known, false);
});

test("metrics sort retrieval first (each base by K), then MRR and context metrics, then generation", () => {
  const shuffled = ["faithfulness", "ndcg@5", "mrr", "recall@10", "citation_correctness", "recall@1", "context_precision", "precision@5", "zzz", "hit_rate@5", "context_recall", "answer_relevance", "recall@5"];
  assert.deepEqual(sortMetricKeys(shuffled), [
    "recall@1", "recall@5", "recall@10", "precision@5", "hit_rate@5", "ndcg@5",
    "mrr", "context_recall", "context_precision",
    "faithfulness", "answer_relevance", "citation_correctness",
    "zzz",
  ]);
  const keys = metricKeysFor([5, 1]);
  assert.equal(keys.length, 4 * 2 + 3 + 5);
  assert.deepEqual(keys.slice(0, 2), ["recall@1", "recall@5"]);
  assert.deepEqual(keys.slice(-5), ["faithfulness", "answer_relevance", "answer_correctness", "citation_correctness", "citation_completeness"]);
  assert.ok(!metricKeysFor([5], { retrievalOnly: true }).includes("faithfulness"));
});

test("a null metric shows its reason and never reads as zero", () => {
  assert.equal(formatMetric(0.8234), "0.82");
  assert.equal(formatMetric(0), "0.00");
  assert.equal(formatMetric(null), "—");
  assert.equal(formatMetric(null, "no_expected_sources"), "— (no expected sources)");
  assert.equal(formatMetric(undefined, "some_new_reason"), "— (some new reason)");
  for (const reason of [
    "no_expected_sources", "expected_sources_unresolved", "empty_context", "item_failed", "retrieval_only", "no_citations",
    "no_expected_source_in_context", "no_expected_answer", "no_answer", "judge_unavailable", "judge_failed",
  ]) {
    const text = reasonText(reason);
    assert.ok(text && !text.includes("_"), `${reason} has a human text`);
  }
  assert.equal(itemMetricText({ mrr: 0.5, faithfulness: null }, { faithfulness: "retrieval_only" }, "faithfulness"), "— (not computed in a retrieval-only experiment)");
  assert.equal(itemMetricText({ mrr: 0.5 }, {}, "mrr"), "0.50");
});

test("aggregates read as mean with the questions behind them and the main null reason", () => {
  assert.deepEqual(formatAggregate({ mean: 0.82, count: 16, null_count: 0, reasons: {} }), { value: "0.82", detail: "16 questions" });
  const partial = { mean: 0.5, count: 16, null_count: 3, reasons: { no_expected_sources: 2, expected_sources_unresolved: 1 } };
  assert.equal(topReason(partial), "no_expected_sources");
  assert.deepEqual(formatAggregate(partial), { value: "0.50", detail: "16 of 19 questions · 3 without a value: no expected sources" });
  assert.deepEqual(formatAggregate({ mean: null, count: 0, null_count: 4, reasons: { retrieval_only: 4 } }), {
    value: "—",
    detail: "0 of 4 questions · 4 without a value: not computed in a retrieval-only experiment",
  });
  assert.deepEqual(formatAggregate({ mean: null, count: 0, null_count: 0, reasons: {} }), { value: "—", detail: "No completed questions yet" });
  assert.deepEqual(formatAggregate(undefined), { value: "—", detail: "Not computed" });
});

// ── Comparison ──────────────────────────────────────────────────────────────

test("deltas are signed, zero has no sign, and tone follows the metric's direction", () => {
  assert.equal(formatSigned(0.1), "+0.10");
  assert.equal(formatSigned(-0.034), `${MINUS}0.03`);
  assert.equal(formatSigned(0), "0.00");
  assert.equal(formatSigned(-0.001), "0.00");
  assert.equal(formatSigned(null), "—");
  assert.equal(deltaTone(0.1, true), "better");
  assert.equal(deltaTone(-0.1, true), "worse");
  assert.equal(deltaTone(120, false), "worse");
  assert.equal(deltaTone(-120, false), "better");
  assert.equal(deltaTone(0, true), "same");
  assert.equal(deltaTone(null, true), "unknown");
});

test("confidence intervals print around the paired difference and say whether they exclude zero", () => {
  assert.equal(formatCi(0.02, 0.18), "[+0.02, +0.18]");
  assert.equal(formatCi(null, 0.1), "");
  assert.equal(ciExcludesZero(0.02, 0.18), true);
  assert.equal(ciExcludesZero(-0.3, -0.01), true);
  assert.equal(ciExcludesZero(-0.02, 0.18), false);
  assert.equal(ciExcludesZero(null, null), false);
  assert.equal(ciText({ delta: 0.1, paired_delta: 0.11, ci_low: 0.02, ci_high: 0.18 }), "+0.11 [+0.02, +0.18]");
  assert.equal(ciText({ delta: 0.1, paired_delta: null, ci_low: null, ci_high: null }), "+0.10");
  assert.equal(ciText({ delta: null, paired_delta: null, ci_low: null, ci_high: null }), "—");
  assert.equal(significance({ ci_low: 0.02, ci_high: 0.18 }, true), "better");
  assert.equal(significance({ ci_low: 0.02, ci_high: 0.18 }, false), "worse");
  assert.equal(significance({ ci_low: -0.2, ci_high: -0.1 }, true), "worse");
  assert.equal(significance({ ci_low: -0.02, ci_high: 0.18 }, true), "inconclusive");
  assert.equal(significance({ ci_low: null, ci_high: null }, true), "unknown");
  assert.equal(winLossText({ wins: 3, losses: 1, ties: 14 }), "3 wins · 1 loss · 14 ties");
  assert.equal(winLossText({ wins: 1, losses: 2, ties: 1 }), "1 win · 2 losses · 1 tie");
  assert.equal(winLossText({ wins: null, losses: null, ties: null }), "—");
});

test("trade-offs weigh quality (its interval when there is one) against latency", () => {
  assert.equal(tradeOff({ qualityDelta: 0.1, latencyDeltaMs: 300, baselineLatencyMs: 400 }).kind, "better_but_slower");
  assert.equal(tradeOff({ qualityDelta: 0.1, latencyDeltaMs: 300, baselineLatencyMs: 400 }).tradeoff, true);
  assert.equal(tradeOff({ qualityDelta: 0.1, latencyDeltaMs: -100, baselineLatencyMs: 400 }).label, "better and faster");
  assert.equal(tradeOff({ qualityDelta: -0.1, latencyDeltaMs: -100, baselineLatencyMs: 400 }).kind, "worse_but_faster");
  assert.equal(tradeOff({ qualityDelta: -0.1, latencyDeltaMs: 100, baselineLatencyMs: 400 }).kind, "worse_and_slower");
  // Within 5% of the baseline latency (or 10 ms) counts as similar latency.
  assert.equal(tradeOff({ qualityDelta: 0.1, latencyDeltaMs: 15, baselineLatencyMs: 400 }).kind, "better_same_speed");
  assert.equal(tradeOff({ qualityDelta: 0.001, latencyDeltaMs: 5 }).kind, "no_clear_difference");
  // An interval that includes zero overrides a positive delta.
  assert.equal(tradeOff({ qualityDelta: 0.1, qualityCi: { low: -0.05, high: 0.2 }, latencyDeltaMs: 300, baselineLatencyMs: 400 }).kind, "same_quality_slower");
  assert.equal(tradeOff({ qualityDelta: 0.001, qualityCi: { low: 0.0005, high: 0.002 }, latencyDeltaMs: -300, baselineLatencyMs: 400 }).kind, "better_and_faster");

  const experiment = (id) => ({ id, name: `E${id}` });
  const comparison = {
    baseline_id: 1,
    experiments: [experiment(1), experiment(2), experiment(3)],
    metrics: [
      {
        key: "recall@5", group: "retrieval", higher_is_better: true,
        cells: [
          { experiment_id: 1, mean: 0.8, delta: null, ci_low: null, ci_high: null },
          { experiment_id: 2, mean: 0.9, delta: 0.1, ci_low: 0.02, ci_high: 0.18 },
          { experiment_id: 3, mean: 0.7, delta: -0.1, ci_low: -0.2, ci_high: -0.01 },
        ],
      },
    ],
    operational: [
      { key: "latency_p50_ms", higher_is_better: false, cells: [{ experiment_id: 1, value: 400, delta: null }, { experiment_id: 2, value: 900, delta: 500 }, { experiment_id: 3, value: 200, delta: -200 }] },
    ],
  };
  assert.deepEqual(comparisonTradeOffs(comparison, "recall@5").map((entry) => [entry.experimentId, entry.kind, entry.tradeoff]), [
    [2, "better_but_slower", true],
    [3, "worse_but_faster", true],
  ]);
  assert.deepEqual(comparisonTradeOffs(null, "recall@5"), []);
});

test("operational values format latency, tokens and cost with signed deltas", () => {
  assert.equal(operationalLabel("latency_p50_ms"), "Latency p50");
  assert.equal(operationalLabel("tokens_per_item"), "Tokens per question");
  assert.equal(formatOperational("latency_p95_ms", 910), "910 ms");
  assert.equal(formatOperational("latency_p95_ms", 2450), "2.45 s");
  assert.equal(formatOperational("total_tokens", 10200), "10,200");
  assert.equal(formatOperational("tokens_per_item", 566.66), "566.7");
  assert.equal(formatOperational("cost_usd", null), "—");
  assert.equal(formatOperationalDelta("latency_p50_ms", 120), "+120 ms");
  assert.equal(formatOperationalDelta("total_tokens", -1200), `${MINUS}1,200`);
  assert.equal(formatOperationalDelta("latency_p50_ms", 0), "0 ms");
  assert.equal(configValueText("hybrid"), "hybrid");
  assert.equal(configValueText([1, 3, 5]), "[1,3,5]");
  assert.equal(configValueText(null), "—");
  assert.equal(configValueText(false), "false");
  assert.equal(compareIdsParam([3, 1, 3, 0, -2, 7]), "3,1,7");
});

// ── Failures ────────────────────────────────────────────────────────────────

test("every failure code of the contract has a label and a category", () => {
  const expected = {
    retrieval: ["relevant_not_retrieved", "wrong_document", "insufficient_k", "query_mismatch"],
    generation: ["unsupported_claim", "citation_mismatch", "incomplete_answer"],
    dataset: ["ambiguous_question", "missing_evidence", "duplicate_question"],
  };
  for (const [category, codes] of Object.entries(expected)) {
    for (const code of codes) {
      const info = FAILURE_CODES.find((item) => item.code === code);
      assert.ok(info, code);
      assert.equal(info.category, category);
      assert.ok(info.label && info.description);
    }
  }
  assert.equal(FAILURE_CODES.length, 10);
  assert.equal(failureLabel("insufficient_k"), "Outside the top-k");
  assert.equal(failureLabel("brand_new_code"), "brand new code");
});

test("labels group by category in a fixed order and counts include every code", () => {
  const labels = [
    { category: "dataset", code: "missing_evidence", detail: "", sources: [1] },
    { category: "retrieval", code: "insufficient_k", detail: "rank 7", sources: [0] },
    { category: "generation", code: "citation_mismatch", detail: "", sources: [] },
    { category: "retrieval", code: "query_mismatch", detail: "", sources: [0] },
  ];
  const groups = groupLabels(labels);
  assert.deepEqual(groups.map((group) => [group.category, group.labels.map((label) => label.code)]), [
    ["retrieval", ["insufficient_k", "query_mismatch"]],
    ["generation", ["citation_mismatch"]],
    ["dataset", ["missing_evidence"]],
  ]);
  assert.deepEqual(groupLabels([]), []);

  const rows = failureCountRows({
    retrieval: { relevant_not_retrieved: 1, insufficient_k: 2 },
    generation: { citation_mismatch: 1, server_only: 4 },
    dataset: {},
    items_with_failures: 3,
  });
  assert.deepEqual(rows.map((row) => [row.category, row.total]), [["retrieval", 3], ["generation", 5], ["dataset", 0]]);
  assert.deepEqual(rows[0].codes.map((code) => [code.code, code.count]), [
    ["relevant_not_retrieved", 1], ["wrong_document", 0], ["insufficient_k", 2], ["query_mismatch", 0],
  ]);
  assert.ok(rows[1].codes.some((code) => code.code === "server_only" && code.count === 4));
  assert.equal(failureCountRows(null)[2].codes.length, 3);

  const options = failureFilterOptions(null);
  assert.equal(options.length, 3 + 10);
  assert.deepEqual(options[0].query, { category: "retrieval" });
  assert.deepEqual(failureFilterQuery("label:insufficient_k"), { label: "insufficient_k" });
  assert.deepEqual(failureFilterQuery("category:dataset"), { category: "dataset" });
  assert.deepEqual(failureFilterQuery("category:bogus"), {});
  assert.deepEqual(failureFilterQuery(""), {});
});

// ── CSV ─────────────────────────────────────────────────────────────────────

test("the CSV reader follows RFC 4180: quotes, escaped quotes, CRLF, line breaks in cells, BOM", () => {
  const text = '\uFEFFa,b,c\r\n"x, y","say ""hi""","line one\nline two"\r\nlast,,\n';
  const { rows, unterminated } = parseCsvRows(text);
  assert.equal(unterminated, false);
  assert.deepEqual(rows, [
    ["a", "b", "c"],
    ["x, y", 'say "hi"', "line one\nline two"],
    ["last", "", ""],
  ]);
  assert.deepEqual(parseCsvRows("a\rb").rows, [["a"], ["b"]]);
  assert.deepEqual(parseCsvRows('a,"b').unterminated, true);
  assert.deepEqual(parseCsvRows("").rows, []);
  assert.deepEqual(parseCsvRows('""').rows, [[""]]);
});

test("a dataset CSV maps columns case-insensitively, skips blank rows and ignores unknown columns", () => {
  const csv = [
    "Question,EXPECTED_ANSWER,expected_sources,tags,notes,item_id",
    'What retrieval method was used?,Hybrid retrieval,12#p6,"methods; retrieval",ignored,q1',
    ",,,,,",
    "",
    'How long is the context window?,,"12#c345,10234-10746; 14#p4-5",,x,',
  ].join("\n");
  const parsed = parseDatasetCsv(csv);
  assert.deepEqual(parsed.errors, []);
  assert.equal(parsed.rows, 2);
  assert.deepEqual(parsed.ignoredColumns, ["notes"]);
  assert.equal(parsed.items.length, 2);
  assert.deepEqual(parsed.items[0], {
    item_id: "q1",
    question: "What retrieval method was used?",
    expected_answer: "Hybrid retrieval",
    expected_sources: [source({ page: 6, page_end: 6 })],
    history: [],
    tags: ["methods", "retrieval"],
    metadata: {},
  });
  assert.equal(parsed.items[1].item_id, undefined);
  assert.deepEqual(parsed.items[1].expected_sources, [
    source({ chunk_id: 345, char_start: 10234, char_end: 10746 }),
    source({ document_id: 14, page: 4, page_end: 5 }),
  ]);
});

test("compact source references cover pages, page ranges, chunks, character ranges and combinations", () => {
  assert.deepEqual(parseCompactSources("12").sources, [source()]);
  assert.deepEqual(parseCompactSources("12#P4").sources, [source({ page: 4, page_end: 4 })]);
  assert.deepEqual(parseCompactSources(" 12 # p4 - 6 ").sources, [source({ page: 4, page_end: 6 })]);
  assert.deepEqual(parseCompactSources("12#c345,p2,100-200").sources, [source({ chunk_id: 345, page: 2, page_end: 2, char_start: 100, char_end: 200 })]);
  assert.equal(parseCompactSources("12#p4; ; 14").sources.length, 2);
  for (const bad of ["abc", "12#q4", "12#p4,p5", "12#200-100", "12#p0", "12#p5-4", "0", "12#"]) {
    const result = parseCompactSources(bad);
    assert.equal(result.sources.length, 0, bad);
    assert.ok(result.errors.length > 0, bad);
  }
  assert.equal(formatCompactSources([source({ page: 4, page_end: 5 }), source({ document_id: 14, chunk_id: 345, char_start: 1, char_end: 9 })]), "12#p4-5; 14#c345,1-9");
  assert.equal(formatCompactSources([source()]), "12");
  assert.equal(formatCompactSources([source({ text: "quote" })]), null);
  assert.equal(formatCompactSources([source({ index_version_id: 7 })]), null);
  assert.equal(describeSource(source({ page: 4, page_end: 5, chunk_id: 9 }), () => "Paper A"), "Paper A · pp. 4–5 · chunk 9");
  assert.equal(describeSource(source({ document_id: null, document_title: "Paper B", char_start: 1, char_end: 5 })), "Paper B · chars 1–5");
});

test("invalid rows are reported with their data row number and field, valid rows still parse", () => {
  const csv = [
    "item_id,question,expected_sources,metadata,history,tags",
    "q1,Fine question,12#p1,,,",
    "bad id!,Second,,,,",
    "q3,,12,,,",
    'q4,Fourth,"[{""document_id"": 12, ""page"": 0}]",,,',
    "q5,Fifth,12#zz,,,",
    "q6,Sixth,,not json,,",
    'q7,Seventh,,,"[{""role"": ""robot"", ""content"": ""hi""}]",',
    "q1,Duplicate id,,,,",
    `q9,${"x".repeat(4001)},,,,`,
    `q10,Tags,,,,${Array.from({ length: 21 }, (_v, index) => `t${index}`).join(";")}`,
  ].join("\n");
  const parsed = parseDatasetCsv(csv);
  assert.equal(parsed.rows, 10);
  assert.deepEqual(parsed.items.map((item) => item.item_id), ["q1"]);
  assert.deepEqual(parsed.errors.map((error) => [error.row, error.field]), [
    [2, "item_id"],
    [3, "question"],
    [4, "expected_sources"],
    [5, "expected_sources"],
    [6, "metadata"],
    [7, "history"],
    [8, "item_id"],
    [9, "question"],
    [10, "tags"],
  ]);
  assert.match(parsed.errors.find((error) => error.row === 8).message, /also used in row 1/);

  const noQuestion = parseDatasetCsv("item_id,answer\nq1,x");
  assert.deepEqual(noQuestion.errors.map((error) => [error.row, error.field]), [[0, "question"]]);
  assert.equal(parseDatasetCsv("   \n\n").errors[0].field, "csv");
  assert.equal(parseDatasetCsv('question\n"open').errors[0].field, "csv");
});

test("JSON source cells and JSON imports are validated with the same rules", () => {
  const csv = 'question,expected_sources\nQ,"[{""document_title"": ""Paper A"", ""char_start"": 5, ""char_end"": 9, ""text"": ""quote""}]"';
  const parsed = parseDatasetCsv(csv);
  assert.deepEqual(parsed.errors, []);
  assert.deepEqual(parsed.items[0].expected_sources, [
    { document_id: null, document_title: "Paper A", chunk_id: null, index_version_id: null, char_start: 5, char_end: 9, page: null, page_end: null, text: "quote" },
  ]);

  const exported = JSON.stringify({
    format: "ragreader-dataset",
    schema_version: 1,
    items: [
      { item_id: "q1", position: 1, question: "A?", expected_answer: "", expected_sources: [{ ...source({ page: 2, page_end: 2 }), document_title: null }], history: [], tags: [], metadata: { level: 1 } },
      { item_id: "q2", position: 2, question: "  ", expected_sources: [] },
      { question: "C?", expected_sources: [{ document_id: 3, color: "red" }] },
      "not an item",
    ],
  });
  const json = parseDatasetJson(exported);
  assert.equal(json.rows, 4);
  assert.deepEqual(json.items, [
    { item_id: "q1", question: "A?", expected_answer: "", expected_sources: [source({ page: 2, page_end: 2 })], history: [], tags: [], metadata: { level: 1 } },
  ]);
  assert.deepEqual(json.errors.map((error) => [error.row, error.field]), [[2, "question"], [3, "expected_sources"], [4, "item"]]);
  assert.match(json.errors[1].message, /Unknown key “color”/);
  assert.equal(parseDatasetJson("[{\"question\": \"Bare list\"}]").items.length, 1);
  assert.equal(parseDatasetJson("{").errors[0].field, "json");
  assert.equal(parseDatasetJson('{"rows": []}').errors[0].field, "json");
  assert.equal(detectFormat("[]", null), "json");
  assert.equal(detectFormat("question\nA", "items.CSV"), "csv");
  assert.equal(detectFormat("\uFEFF{\"items\": []}"), "json");
  assert.equal(parseDatasetFile("question\nA").format, "csv");
});

test("exported CSV parses back to the same items", () => {
  const items = [
    {
      item_id: "q1",
      question: 'Which "method", exactly?',
      expected_answer: "Hybrid,\nwith reranking",
      expected_sources: [source({ page: 6, page_end: 7, chunk_id: 345, text: "a quoted, multi\nline passage" }), source({ document_id: 14, index_version_id: 7 })],
      history: [{ role: "user", content: "Tell me about the paper." }, { role: "assistant", content: "It studies retrieval." }],
      tags: ["methods", "hard case"],
      metadata: { source: "chat", ids: [1, 2] },
    },
    { item_id: "q2", question: "Plain?", expected_answer: "", expected_sources: [], history: [], tags: [], metadata: {} },
  ];
  const csv = toCsv(items);
  assert.ok(csv.startsWith("item_id,question,expected_answer,expected_sources,tags,metadata,history\r\n"));
  const parsed = parseDatasetCsv(csv);
  assert.deepEqual(parsed.errors, []);
  assert.deepEqual(parsed.items, items);
});

test("item validation mirrors the server's limits", () => {
  assert.deepEqual(validateItemInput({ question: "  Why?  " }).item, { question: "Why?", expected_answer: "", expected_sources: [], history: [], tags: [], metadata: {} });
  const field = (raw) => validateItemInput(raw).errors.map((error) => error.field);
  assert.deepEqual(field({ question: "" }), ["question"]);
  assert.deepEqual(field({ question: "Q", item_id: "-bad" }), ["item_id"]);
  assert.deepEqual(field({ question: "Q", item_id: "a".repeat(65) }), ["item_id"]);
  assert.deepEqual(field({ question: "Q", item_id: "Q-1.a:b_c" }), []);
  assert.deepEqual(field({ question: "Q", expected_answer: "x".repeat(20001) }), ["expected_answer"]);
  assert.deepEqual(field({ question: "Q", expected_sources: Array.from({ length: 21 }, () => source()) }), ["expected_sources"]);
  assert.deepEqual(field({ question: "Q", expected_sources: [source({ char_start: 5 })] }), ["expected_sources"]);
  assert.deepEqual(field({ question: "Q", expected_sources: [source({ page_end: 3 })] }), ["expected_sources"]);
  assert.deepEqual(field({ question: "Q", expected_sources: [source({ text: "x".repeat(1001) })] }), ["expected_sources"]);
  assert.deepEqual(field({ question: "Q", tags: ["x".repeat(51)] }), ["tags"]);
  assert.deepEqual(validateItemInput({ question: "Q", tags: [" a ", "a", "", "b"] }).item.tags, ["a", "b"]);
  assert.deepEqual(field({ question: "Q", history: Array.from({ length: 7 }, () => ({ role: "user", content: "x" })) }), ["history"]);
  assert.deepEqual(field({ question: "Q", metadata: [1] }), ["metadata"]);
  assert.deepEqual(field({ question: "Q", metadata: { blob: "x".repeat(9000) } }), ["metadata"]);
});

// ── Item form ───────────────────────────────────────────────────────────────

test("source drafts round-trip and report bad numbers; answers' evidence becomes expected sources", () => {
  const original = source({ page: 3, page_end: 4, chunk_id: 9, char_start: 10, char_end: 20, index_version_id: 7, text: "q" });
  assert.deepEqual(fromSourceDraft(toSourceDraft(original)).source, original);
  const draft = { ...toSourceDraft(source()), chunk_id: "abc" };
  assert.match(fromSourceDraft(draft).errors.join(" "), /chunk_id/);
  assert.deepEqual(tagsFromText("a; b, a ,, c"), ["a", "b", "c"]);

  const evidence = {
    citation_id: 2, document_id: 12, document_title: "Paper", index_version_id: 7, chunk_id: 345,
    page_number: 6, page_end: 6, char_start: 100, char_end: 300, text: "x".repeat(1500),
    retrieval_score: 0.8, rerank_score: null, cited: true, suggested: true,
  };
  const built = evidenceToExpected(evidence);
  assert.deepEqual({ ...built, text: built.text.length }, {
    document_id: 12, chunk_id: 345, index_version_id: 7, char_start: 100, char_end: 300, page: 6, page_end: 6, text: 1000,
  });
  const drafted = source({ chunk_id: 345, page: 6, page_end: 6, text: "server draft" });
  assert.equal(evidenceToExpected(evidence, [drafted]), drafted);
  const bare = evidenceToExpected({ ...evidence, chunk_id: "legacy-x", page_number: null, char_start: null });
  assert.deepEqual([bare.chunk_id, bare.page, bare.char_start], [null, null, null]);
});

// ── Experiments ─────────────────────────────────────────────────────────────

test("statuses decide polling and the actions offered", () => {
  assert.equal(statusLabel("running"), "Running");
  assert.equal(statusLabel("mystery"), "mystery");
  assert.deepEqual(["draft", "queued", "running", "completed", "failed", "cancelled"].map(isActive), [false, true, true, false, false, false]);
  assert.deepEqual(experimentActions("draft"), { start: true, resume: false, cancel: false, rerun: false });
  assert.deepEqual(experimentActions("queued"), { start: false, resume: false, cancel: true, rerun: false });
  assert.deepEqual(experimentActions("running"), { start: false, resume: false, cancel: true, rerun: false });
  assert.deepEqual(experimentActions("completed"), { start: false, resume: false, cancel: false, rerun: true });
  assert.deepEqual(experimentActions("failed"), { start: false, resume: true, cancel: false, rerun: true });
  assert.deepEqual(experimentActions("cancelled"), { start: false, resume: true, cancel: false, rerun: true });
});

test("progress, headline metrics, K values and seeds", () => {
  const progress = { total: 20, completed: 5, failed: 1, pending: 14 };
  assert.equal(progressFraction(progress), 0.3);
  assert.equal(progressText(progress), "6 of 20 questions · 1 failed");
  assert.equal(progressFraction({ total: 0, completed: 0, failed: 0, pending: 0 }), 0);
  assert.equal(progressText({ total: 1, completed: 1, failed: 0, pending: 0 }), "1 of 1 question");

  const metrics = {
    retrieval: { "recall@5": { mean: 0.91, count: 4, null_count: 0, reasons: {} }, mrr: { mean: 0.84, count: 4, null_count: 0, reasons: {} } },
    generation: { faithfulness: { mean: null, count: 0, null_count: 4, reasons: { judge_failed: 4 } } },
  };
  assert.deepEqual(headlineMetrics({ metrics, k_values: [1, 3, 5, 10], retrieval_only: false }), [
    { key: "recall@5", label: "Recall@5", value: "0.91" },
    { key: "mrr", label: "MRR", value: "0.84" },
    { key: "ndcg@5", label: "nDCG@5", value: "—" },
    { key: "faithfulness", label: "Faithfulness", value: "—" },
  ]);
  assert.deepEqual(headlineMetrics({ metrics, k_values: [10, 3], retrieval_only: true }).map((metric) => metric.key), ["recall@3", "mrr", "ndcg@3"]);
  assert.deepEqual(headlineMetrics({ metrics: null, k_values: [20], retrieval_only: true }).map((metric) => metric.key), ["recall@20", "mrr", "ndcg@20"]);

  assert.deepEqual(parseKValues("10, 1 3;5 5"), { values: [1, 3, 5, 10], error: null });
  assert.ok(parseKValues("").error);
  assert.ok(parseKValues("0").error);
  assert.ok(parseKValues("51").error);
  assert.ok(parseKValues("1.5").error);
  assert.ok(parseKValues("1 2 3 4 5 6 7").error);
  assert.deepEqual(parseSeed(""), { value: 42, error: null });
  assert.deepEqual(parseSeed(" 7 "), { value: 7, error: null });
  assert.ok(parseSeed("-1").error);
  assert.ok(parseSeed(String(2 ** 31)).error);
});

test("the comparison selection holds at most six experiments of one dataset", () => {
  let selected = [];
  for (let id = 1; id <= 8; id += 1) selected = toggleCompare(selected, id);
  assert.equal(MAX_COMPARE, 6);
  assert.deepEqual(selected, [1, 2, 3, 4, 5, 6]);
  assert.deepEqual(toggleCompare(selected, 3), [1, 2, 4, 5, 6]);
  const on = (id) => ({ dataset: { id } });
  assert.equal(sameDataset([on(5), on(5)]), true);
  assert.equal(sameDataset([on(5), on(6)]), false);
  assert.equal(sameDataset([on(5), on(null)]), true);
  assert.equal(warningTitle("repeated_dataset_runs"), "Many runs on one test set");
  assert.equal(warningTitle("something_new"), "something new");
});

test("evaluation and experiment endpoints are token-protected paths", () => {
  for (const path of [
    "/evaluations/datasets/",
    "/api/v1/evaluations/datasets/5/items/from-message/?message_id=1",
    "evaluations/datasets/import/",
    "/experiments/",
    "/experiments/compare/?ids=1,2",
    "/api/v1/experiments/42/items/",
  ]) {
    assert.equal(isProtectedApiPath(path), true, path);
  }
  // The legacy evaluate endpoints stay protected, and look-alike names do not match.
  assert.equal(isProtectedApiPath("/evaluate/ground-truth-chunk/"), true);
  assert.equal(isProtectedApiPath("/experimentsx/"), false);
  assert.equal(isProtectedApiPath("/sign-in/"), false);
});
