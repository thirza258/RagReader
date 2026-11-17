"""Pure metric, matching, failure and comparison functions on hand-computed examples."""
import math
import os
from types import SimpleNamespace

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

from django.test import SimpleTestCase

from lab.services import comparison, failures, matching
from lab.services import metrics as m


class RetrievalMetricTests(SimpleTestCase):
    ranked = [10, 20, 30, 40]
    sources = [{20}, {40, 50}]

    def metrics(self, ranked=None, sources=None, k_values=(1, 2, 5), context_size=2, has=True):
        return m.retrieval_metrics(self.ranked if ranked is None else ranked,
                                   self.sources if sources is None else sources, list(k_values), context_size,
                                   has_expected_sources=has)

    def test_hand_computed_values(self):
        values, reasons = self.metrics()
        self.assertEqual((values["recall@1"], values["recall@2"], values["recall@5"]), (0.0, 0.5, 1.0))
        self.assertEqual((values["precision@2"], values["precision@5"]), (0.5, 0.4))  # ÷ K even past the list
        self.assertEqual((values["hit_rate@1"], values["hit_rate@2"]), (0.0, 1.0))
        self.assertEqual(values["mrr"], 0.5)
        ideal = 1 + 1 / math.log2(3)
        self.assertAlmostEqual(values["ndcg@5"], (1 / math.log2(3) + 1 / math.log2(5)) / ideal, places=6)
        self.assertEqual((values["context_recall"], values["context_precision"]), (0.5, 0.5))
        self.assertEqual(reasons, {})

    def test_a_repeated_chunk_counts_once(self):
        values, _ = self.metrics(ranked=[20, 20, 30])
        self.assertEqual(values["precision@2"], 0.5)  # [20, 30] after de-duplication

    def test_no_expected_sources_and_unresolved_sources_are_null_with_a_reason(self):
        values, reasons = self.metrics(sources=[], has=False)
        self.assertTrue(all(value is None for value in values.values()))
        self.assertEqual(set(reasons.values()), {m.NO_EXPECTED_SOURCES})
        _values, reasons = self.metrics(sources=[], has=True)
        self.assertEqual(set(reasons.values()), {m.SOURCES_UNRESOLVED})

    def test_an_empty_context_has_no_precision(self):
        values, reasons = self.metrics(context_size=0)
        self.assertIsNone(values["context_precision"])
        self.assertEqual(reasons["context_precision"], m.EMPTY_CONTEXT)
        self.assertEqual(values["context_recall"], 0.0)


class CitationMetricTests(SimpleTestCase):
    def test_correctness_and_completeness(self):
        values, reasons = m.citation_metrics([10, 20, 40], [20, 10], [{20}, {40}], has_expected_sources=True)
        self.assertEqual(values["citation_correctness"], 0.5)
        self.assertEqual(values["citation_completeness"], 0.5)  # 1 of the 2 sources in context was cited
        self.assertEqual(reasons, {})

    def test_reasons(self):
        values, reasons = m.citation_metrics([10], [], [{20}], has_expected_sources=True)
        self.assertEqual(reasons, {"citation_correctness": m.NO_CITATIONS,
                                   "citation_completeness": m.NO_SOURCE_IN_CONTEXT})
        self.assertEqual(values, {"citation_correctness": None, "citation_completeness": None})


class MatchingTests(SimpleTestCase):
    def corpus(self):
        positions = {
            1: {"char_start": 0, "char_end": 50, "page_start": 1, "page_end": 1},
            2: {"char_start": 50, "char_end": 100, "page_start": 1, "page_end": 2},
            3: {"char_start": 100, "char_end": 150, "page_start": 3, "page_end": 3},
        }
        return {7: matching.IndexChunks(document_id=7, index_version_id=70, chunk_ids=(1, 2, 3), positions=positions)}

    def test_each_rule_in_order(self):
        corpus = self.corpus()
        cases = [
            ({"document_id": 7, "chunk_id": 2}, ("chunk_id", [2])),
            ({"document_id": 7, "chunk_id": 99, "char_start": 60, "char_end": 120}, ("char_overlap", [2, 3])),
            ({"document_id": 7, "chunk_id": 99, "page": 2}, ("page", [2])),
            ({"document_id": 7}, ("document", [1, 2, 3])),
            ({"document_id": 8}, ("unresolved", [])),
            ({"document_id": 7, "chunk_id": 99}, ("unresolved", [])),
        ]
        for source, (rule, chunk_ids) in cases:
            with self.subTest(source=source):
                result = matching.resolve_source(source, corpus)
                self.assertEqual((result["rule"], result["chunk_ids"]), (rule, chunk_ids))
        self.assertEqual(matching.resolve_source({"document_id": 8}, corpus)["reason"], matching.NOT_IN_CORPUS)
        self.assertEqual(matching.resolve_source({"document_id": 7, "chunk_id": 99}, corpus)["reason"],
                         matching.CHUNK_NOT_IN_INDEX)


class FailureLabelTests(SimpleTestCase):
    def codes(self, labels):
        return [label["code"] for label in labels]

    def test_retrieval_categories(self):
        ranked = [{"chunk_id": 1, "document_id": 9}, {"chunk_id": 2, "document_id": 9}, {"chunk_id": 3, "document_id": 7}]
        # Source 0 (chunk 5) is nowhere; source 1 (chunk 3) ranked 3, outside a context of 2 passages
        # whose documents no expected source names.
        labels = failures.retrieval_labels([(0, {5}), (1, {3})], ranked, 2, {7})
        self.assertEqual(self.codes(labels), ["relevant_not_retrieved", "insufficient_k", "wrong_document"])
        alternative = {"kind": "original", "ranked": [{"chunk_id": 3, "document_id": 7}], "context_size": 1}
        labels = failures.retrieval_labels([(0, {3})], ranked, 2, {7}, alternative)
        self.assertIn("query_mismatch", self.codes(labels))

    def test_generation_and_dataset_categories(self):
        thresholds = {"faithfulness": 0.5, "answer_correctness": 0.5}
        labels = failures.generation_labels({"faithfulness": 0.2, "citation_correctness": 0.5,
                                             "answer_correctness": 0.1}, thresholds)
        self.assertEqual(self.codes(labels), ["unsupported_claim", "citation_mismatch", "incomplete_answer"])
        labels = failures.dataset_labels(0, [{"source": 0, "rule": "unresolved", "reason": "x"}], ["q9"])
        self.assertEqual(self.codes(labels), ["ambiguous_question", "missing_evidence", "duplicate_question"])
        counts = failures.count_labels([labels, []])
        self.assertEqual((counts["dataset"]["ambiguous_question"], counts["items_with_failures"]), (1, 1))


class BootstrapTests(SimpleTestCase):
    def test_paired_bootstrap_is_deterministic_for_a_seed(self):
        differences = [0.1, 0.0, 0.2, -0.1, 0.3, 0.1]
        first = comparison.paired_bootstrap(differences, seed=42)
        self.assertEqual(first, comparison.paired_bootstrap(differences, seed=42))
        low, high = first
        self.assertLess(low, sum(differences) / len(differences))
        self.assertGreater(high, sum(differences) / len(differences))

    def test_compare_cell_counts_wins_losses_and_ties(self):
        baseline = {("q1", "a"): 1.0, ("q2", "b"): 0.0, ("q3", "c"): 0.5, ("q4", "d"): None}
        other = {("q1", "a"): 1.0, ("q2", "b"): 1.0, ("q3", "c"): 0.0, ("q4", "d"): 1.0}
        cell = comparison.compare_cell(baseline, other, seed=1)
        self.assertEqual((cell["pairs"], cell["wins"], cell["losses"], cell["ties"]), (3, 1, 1, 1))
        self.assertAlmostEqual(cell["paired_delta"], (0 + 1 - 0.5) / 3, places=6)

    def test_too_few_pairs_have_no_interval(self):
        cell = comparison.compare_cell({("q1", "a"): 0.0}, {("q1", "a"): 1.0}, seed=1)
        self.assertEqual((cell["ci_low"], cell["ci_high"]), (None, None))
