"""Phase 3 retrieval: dense, BM25, hybrid fusion and reranking (PRD §17–18, §21, §32).

The pure parts (pooling, fusion math, BM25 over a union corpus, reranking,
the LLM reranker's prompt and parser) are tested on hand-built snapshots;
the strategies end to end run through real ingestion and the chat turn with
the keyword embeddings of `helpers.keyword_vector` and fake LLM clients.
"""
import json
from types import SimpleNamespace
from unittest import mock

import numpy as np
from django.test import SimpleTestCase, override_settings
from rank_bm25 import BM25Okapi

from ai_handler.llm import OpenRouterLLM
from common.constant import LLM_RERANK_PROMPT_CHARS
from hybrid_rag.hybrid_rag import RerankUnavailable
from sparse_rag.sparse_rag import english_stop_words, tokenize
from workspace.models import RetrievalRun, Workspace
from workspace.services import index_cache, llms, pipelines, retrieval
from workspace.services.index_cache import Bm25Index, IndexSnapshot
from workspace.services.rerankers import LLMReranker, RerankFailed, parse_scores, rerank_prompt
from workspace.tests.helpers import FakeChat, keyword_vector
from workspace.tests.test_runs import RunTestCase, by_name

# Each paragraph is 31–60 characters, so the test chunker (paragraph, size 60)
# makes exactly one passage of each. Keyword axes: alpha … zeta.
DOC_A = [
    "Alpha and gamma appear together in this one.",   # both query terms: first for dense and BM25
    "Alpha alpha alpha alpha, said the long refrain.",  # alpha ×4
    "Delta is unrelated to the question being asked.",  # no query term (delta axis)
]
DOC_B = [
    "Gamma rays are a kind of radiation, said Ann.",    # gamma only
    "Zeta and epsilon are later letters of the set.",   # no query term (two other axes)
    "Beta is the second letter of the Greek letters.",  # no query term (beta axis)
]
# Cosine: both terms (1.0) > one term (0.71, A before B) > one other axis
# (0.0018, A before B) > two other axes (0.0012). BM25 (k1 1.5, b 0.75, stop
# words removed): A0 1.21 > A1 1.00 > B0 0.56; the rest do not match.
DENSE_ORDER = [DOC_A[0], DOC_A[1], DOC_B[0], DOC_A[2], DOC_B[2], DOC_B[1]]
BM25_ORDER = [DOC_A[0], DOC_A[1], DOC_B[0]]
QUERY = "alpha gamma"


def snapshot(vector_id, texts, chunk_ids=None):
    matrix = np.array([keyword_vector(text) for text in texts], dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix.setflags(write=False)
    ids = tuple(chunk_ids or range(vector_id * 100, vector_id * 100 + len(texts)))
    return IndexSnapshot(vector_id=vector_id, texts=tuple(texts), chunk_ids=ids, matrix=matrix)


def loaded(*snapshots):
    return [
        retrieval.Loaded(order=order, document=SimpleNamespace(pk=order + 1, name=f"Doc {order + 1}"),
                         vector=SimpleNamespace(pk=snap.vector_id, vectorstore_location=f"/x/{snap.vector_id}"), snapshot=snap)
        for order, snap in enumerate(snapshots)
    ]


def query_vector(text):
    vector = np.asarray(keyword_vector(text), dtype=np.float32)
    return vector / np.linalg.norm(vector)


def texts_of(items):
    return [item[3].snapshot.texts[item[2]] for item in items]


class RankingMathTests(SimpleTestCase):
    def setUp(self):
        self.entries = loaded(snapshot(1, DOC_A), snapshot(2, DOC_B))
        q = query_vector(QUERY)
        self.dense = {entry.order: entry.snapshot.matrix @ q for entry in self.entries}
        index = Bm25Index([entry.snapshot for entry in self.entries])
        by_vector = index.scores(QUERY, [entry.snapshot for entry in self.entries])
        self.bm25 = {entry.order: by_vector[entry.snapshot.vector_id] for entry in self.entries}

    def rankings(self, depth=20):
        dense, _ = retrieval.unique_ranking(retrieval.pool(self.entries, self.dense, depth), depth)
        bm25, _ = retrieval.unique_ranking(retrieval.pool(self.entries, self.bm25, depth, keep=lambda v: v > 0), depth)
        return dense, bm25

    def test_dense_and_bm25_orders_on_the_hand_built_corpus(self):
        dense, bm25 = self.rankings()
        # Cosine of keyword vectors: both keywords, then one keyword (tie →
        # document order), then none (tie → document order, then position).
        self.assertEqual(texts_of(dense), DENSE_ORDER)
        # BM25 only returns passages containing a query term.
        self.assertEqual(texts_of(bm25), BM25_ORDER)
        scores = [item[0] for item in bm25]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(score > 0 for score in scores))

    def test_rrf_scores_are_the_sum_of_reciprocal_ranks(self):
        dense, bm25 = self.rankings()
        fused = retrieval.fuse(dense, bm25, method="rrf", hybrid_weight=0.6, rrf_k=60,
                               dense_scores=self.dense, bm25_scores=self.bm25)
        dense_rank = {text: rank for rank, text in enumerate(texts_of(dense), 1)}
        bm25_rank = {text: rank for rank, text in enumerate(texts_of(bm25), 1)}
        expected = {
            text: 1 / (60 + dense_rank[text]) + (1 / (60 + bm25_rank[text]) if text in bm25_rank else 0.0)
            for text in dense_rank
        }
        got = {row[3].snapshot.texts[row[2]]: row[0] for row in fused}
        self.assertEqual(set(got), set(expected))
        for text, score in expected.items():
            self.assertAlmostEqual(got[text], score, places=12)
        self.assertEqual([row[0] for row in fused], sorted(got.values(), reverse=True))
        # Components are the raw scores of both retrievers, for every passage.
        for row in fused:
            order, position = row[1], row[2]
            self.assertAlmostEqual(row[4], float(self.dense[order][position]), places=6)
            self.assertAlmostEqual(row[5], float(self.bm25[order][position]), places=9)

    def test_weighted_fusion_normalises_each_retriever_and_mixes_by_the_hybrid_weight(self):
        dense, bm25 = self.rankings()
        fused = retrieval.fuse(dense, bm25, method="weighted", hybrid_weight=0.6, rrf_k=60,
                               dense_scores=self.dense, bm25_scores=self.bm25)
        dense_raw = [row[4] for row in fused]
        bm25_raw = [row[5] for row in fused]
        for row in fused:
            d = (row[4] - min(dense_raw)) / (max(dense_raw) - min(dense_raw))
            b = (row[5] - min(bm25_raw)) / (max(bm25_raw) - min(bm25_raw))
            self.assertAlmostEqual(row[0], 0.6 * d + 0.4 * b, places=9)
        # Hand-checkable: the passage with both keywords tops both lists.
        self.assertEqual(fused[0][3].snapshot.texts[fused[0][2]], DOC_A[0])
        self.assertAlmostEqual(fused[0][0], 1.0, places=9)

    def test_hybrid_weight_one_and_zero_reduce_to_the_single_retriever(self):
        dense, bm25 = self.rankings()
        only_dense = retrieval.fuse(dense, bm25, method="weighted", hybrid_weight=1.0, rrf_k=60,
                                    dense_scores=self.dense, bm25_scores=self.bm25)
        only_bm25 = retrieval.fuse(dense, bm25, method="weighted", hybrid_weight=0.0, rrf_k=60,
                                   dense_scores=self.dense, bm25_scores=self.bm25)
        self.assertEqual([(row[1], row[2]) for row in only_dense], [(item[1], item[2]) for item in dense])
        self.assertEqual([(row[1], row[2]) for row in only_bm25], [(item[1], item[2]) for item in bm25])

    def test_all_equal_scores_normalise_to_one(self):
        self.assertEqual(retrieval._normalised([0.3, 0.3]), [1.0, 1.0])
        self.assertEqual(retrieval._normalised([1.0, 3.0, 2.0]), [0.0, 1.0, 0.5])

    def test_duplicates_across_documents_are_kept_once(self):
        entries = loaded(snapshot(1, [DOC_A[0], DOC_A[1]]), snapshot(2, [DOC_A[0], DOC_B[0]]))
        q = query_vector(QUERY)
        scores = {entry.order: entry.snapshot.matrix @ q for entry in entries}
        kept, duplicates = retrieval.unique_ranking(retrieval.pool(entries, scores, 20), 20)
        self.assertEqual(duplicates, 1)
        self.assertEqual(texts_of(kept), [DOC_A[0], DOC_A[1], DOC_B[0]])
        self.assertEqual((kept[0][1], kept[0][2]), (0, 0))  # the first document's copy


class Bm25UnionTests(SimpleTestCase):
    def setUp(self):
        index_cache.clear()
        self.addCleanup(index_cache.clear)

    def test_scores_come_from_one_index_over_the_union_of_documents(self):
        first, second = snapshot(7, DOC_A), snapshot(3, DOC_B)
        union = Bm25Index([first, second])
        stop_words = english_stop_words()
        # The reference: one BM25Okapi over every passage, index-version order.
        reference = BM25Okapi([tokenize(text, stop_words) for text in DOC_B + DOC_A])
        expected = reference.get_scores(tokenize(QUERY, stop_words))
        scores = union.scores(QUERY, [first, second])
        np.testing.assert_allclose(scores[3], expected[:3])
        np.testing.assert_allclose(scores[7], expected[3:])
        # Independent of the order the documents are given in.
        swapped = Bm25Index([second, first]).scores(QUERY, [second, first])
        np.testing.assert_allclose(swapped[7], scores[7])

    def test_the_same_passage_scores_the_same_in_any_document(self):
        shared = "Gamma rays are a kind of radiation, said Ann."
        rare = snapshot(1, [shared, "Zeta and epsilon are later letters of the set."])
        common = snapshot(2, ["Gamma again, now in a second gamma passage.", shared, "Gamma gamma once more, a third gamma one."])
        union = Bm25Index([rare, common]).scores("gamma radiation", [rare, common])
        self.assertAlmostEqual(float(union[1][0]), float(union[2][1]), places=12)
        # Indexed separately the same passage would not be comparable.
        alone = [BM25Okapi([tokenize(t, english_stop_words()) for t in snap.texts]) for snap in (rare, common)]
        terms = tokenize("gamma radiation", english_stop_words())
        self.assertNotAlmostEqual(alone[0].get_scores(terms)[0], alone[1].get_scores(terms)[1], places=3)

    def test_the_built_index_is_cached_by_the_set_of_index_versions_and_evicted(self):
        first, second = snapshot(1, DOC_A), snapshot(2, DOC_B)
        built, hit = index_cache.fetch_bm25([first, second])
        self.assertFalse(hit)
        again, hit = index_cache.fetch_bm25([second, first])
        self.assertTrue(hit)
        self.assertIs(again, built)
        _, hit = index_cache.fetch_bm25([first])
        self.assertFalse(hit)  # another set is another index
        index_cache.discard([2])
        _, hit = index_cache.fetch_bm25([first, second])
        self.assertFalse(hit)

    def test_queries_without_terms_and_corpora_without_tokens_score_zero(self):
        stop_words_only = snapshot(1, ["The of and a is to.", "And the was of it."])
        self.assertEqual(Bm25Index([stop_words_only]).scores("alpha", [stop_words_only])[1].tolist(), [0.0, 0.0])
        letters = snapshot(2, DOC_A)
        self.assertEqual(Bm25Index([letters]).scores("the of", [letters])[2].tolist(), [0.0, 0.0, 0.0])


class FakeReranker:
    def __init__(self, scores=None, error=None):
        self.scores, self.error, self.calls = scores, error, []

    def score(self, query, texts):
        self.calls.append((query, list(texts)))
        if self.error is not None:
            raise self.error
        return [float(value) for value in self.scores[:len(texts)]]


class RerankAndLlmRerankerTests(SimpleTestCase):
    def candidates(self, count):
        snap = snapshot(1, [f"Passage number {n} about alpha and more words." for n in range(count)])
        return [retrieval.Candidate(order=0, position=n, document=None, vector=None, snapshot=snap, retrieval_rank=n + 1, rank=n + 1)
                for n in range(count)]

    def test_rerank_reorders_by_score_and_keeps_ties_in_fused_order(self):
        items = self.candidates(4)
        ranked = retrieval.rerank(FakeReranker([0.1, 0.9, 0.5, 0.9]), "q", items)
        self.assertEqual([item.position for item in ranked], [1, 3, 2, 0])
        self.assertEqual([item.rerank_score for item in ranked], [0.9, 0.9, 0.5, 0.1])

    def test_a_short_score_list_is_an_error(self):
        with self.assertRaises(Exception):
            retrieval.rerank(FakeReranker([0.1]), "q", self.candidates(3))

    def test_the_prompt_is_bounded_and_numbers_every_passage(self):
        texts = ["word " * 2000 for _ in range(50)]
        prompt = rerank_prompt("query " * 500, texts)
        self.assertLess(len(prompt), LLM_RERANK_PROMPT_CHARS + 2500)
        for number in (1, 25, 50):
            self.assertIn(f"\n[{number}] ", prompt)
        self.assertIn('"scores"', prompt)

    def test_strict_parsing(self):
        self.assertEqual(parse_scores('{"scores": [{"id": 2, "score": 5}, {"id": 1, "score": 10}]}', 2), [1.0, 0.5])
        self.assertEqual(parse_scores('```json\n[{"id": 1, "score": 0}]\n```', 1), [0.0])
        bad = [
            "not json", '{"scores": "x"}', '{"scores": [{"id": 1, "score": 5}]}',          # missing id 2
            '{"scores": [{"id": 1, "score": 5}, {"id": 1, "score": 4}]}',                    # repeated
            '{"scores": [{"id": 1, "score": 5}, {"id": 3, "score": 4}]}',                    # unknown
            '{"scores": [{"id": 1, "score": 11}, {"id": 2, "score": 4}]}',                   # out of range
            '{"scores": [{"id": 1, "score": true}, {"id": 2, "score": 4}]}',                 # not a number
            '{"scores": [{"id": "1", "score": 3}, {"id": 2, "score": 4}]}',                  # id not an int
            'Sure! {"scores": [{"id": 1, "score": 3}, {"id": 2, "score": 4}]}',              # prose around JSON
        ]
        for reply in bad:
            with self.assertRaises(RerankFailed, msg=reply) as caught:
                parse_scores(reply, 2)
            self.assertEqual(caught.exception.code, "reranker_invalid_response")

    def test_the_llm_reranker_asks_its_model_once(self):
        fake = mock.Mock()
        fake.generate.return_value = json.dumps({"scores": [{"id": 1, "score": 2}, {"id": 2, "score": 8}]})
        with mock.patch.object(llms, "llm_for", return_value=fake) as factory:
            scores = LLMReranker("vendor/judge").score("alpha", ["one passage text", "two passage text"])
        factory.assert_called_once_with("vendor/judge")
        self.assertEqual(scores, [0.2, 0.8])
        self.assertEqual(fake.generate.call_count, 1)


# ── End to end through ingestion and the chat turn ───────────────────────────

class StrategyTestCase(RunTestCase):
    def setUp(self):
        super().setUp()
        llms.clear()
        self.addCleanup(llms.clear)
        self.doc_a = self.ready_text_document("\n\n".join(DOC_A), title="Letters A")
        self.doc_b = self.ready_text_document("\n\n".join(DOC_B), title="Letters B")

    def make_pipeline(self, **config):
        response = self.post("/api/v1/pipelines/", {"name": f"P {config.get('strategy')}", "config": config})
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def ask_with(self, pipeline, question=QUERY):
        conversation = self.conversation(pipeline_id=pipeline["id"]) if pipeline else self.conversation()
        _, events = self.ask(conversation["id"], question)
        completed = self.event(events, "message.completed")
        self.assertEqual(len(completed), 1, events)
        return completed[0]["message"], events

    def texts(self, message):
        run = RetrievalRun.objects.get(pk=message["retrieval"]["run_id"])
        return [candidate.snippet for candidate in run.candidates.order_by("rank")], run


class StrategyTests(StrategyTestCase):
    def test_dense_ranks_by_cosine_and_is_the_default(self):
        message, _ = self.ask_with(None)
        texts, run = self.texts(message)
        self.assertEqual(texts, DENSE_ORDER)
        candidates = message["retrieval"]["candidates"]
        self.assertTrue(all(c["bm25_score"] is None and c["fused_score"] is None for c in candidates))
        self.assertEqual([c["dense_score"] for c in candidates], [c["retrieval_score"] for c in candidates])
        self.assertEqual(run.provenance["pipeline"]["name"], "Default (dense)")

    def test_bm25_returns_only_keyword_matches_and_skips_the_query_embedding(self):
        pipeline = self.make_pipeline(strategy="bm25")
        before = len(self.embeddings.calls)
        message, events = self.ask_with(pipeline)
        self.assertEqual(len(self.embeddings.calls), before)  # nothing embedded for BM25
        texts, run = self.texts(message)
        self.assertEqual(texts, BM25_ORDER)
        scores = [c["bm25_score"] for c in message["retrieval"]["candidates"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(c["dense_score"] is None for c in message["retrieval"]["candidates"]))
        self.assertEqual(message["retrieval"]["pipeline"]["strategy"], "bm25")
        spans = by_name(self.detail(run.pk)["spans"])
        self.assertEqual([child["name"] for child in spans["retrieve"]["children"]],
                         ["retrieve.load_indexes", "retrieve.bm25", "retrieve.select"])
        self.assertEqual((spans["retrieve.bm25"]["data"]["cache"], spans["retrieve.bm25"]["data"]["matched"]), ("miss", 3))
        self.assertEqual(run.provenance["retrieval_parameters"]["similarity"], "bm25")
        # The second question over the same documents reuses the built index.
        conversation = message["conversation_id"]
        _, events = self.ask(conversation, "gamma radiation")
        run_id = self.event(events, "message.completed")[0]["run_id"]
        self.assertEqual(by_name(self.detail(run_id)["spans"])["retrieve.bm25"]["data"]["cache"], "hit")

    def test_bm25_with_no_matching_passage_answers_from_no_sources(self):
        pipeline = self.make_pipeline(strategy="bm25")
        message, _ = self.ask_with(pipeline, "omega")
        self.assertEqual((message["status"], message["retrieval"]["candidate_count"], message["citations"]), ("complete", 0, []))
        self.assertIn("No passages were found", self.chat.stream_calls[-1]["messages"][-1]["content"])

    def test_hybrid_rrf_fuses_both_rankings(self):
        pipeline = self.make_pipeline(strategy="hybrid", fusion="rrf", rrf_k=10, candidate_k=6, top_k=3)
        message, _ = self.ask_with(pipeline)
        candidates = message["retrieval"]["candidates"]
        self.assertEqual(len(candidates), 6)
        fused = [c["fused_score"] for c in candidates]
        self.assertEqual(fused, sorted(fused, reverse=True))
        self.assertEqual([c["retrieval_score"] for c in candidates], fused)
        # Passages BM25 did not return get only their dense contribution.
        for c in candidates:
            self.assertIsNotNone(c["dense_score"])
            self.assertIsNotNone(c["bm25_score"])
            if c["bm25_score"] == 0:
                self.assertLessEqual(c["fused_score"], 1 / 11 + 1e-9)
        texts, run = self.texts(message)
        self.assertEqual(texts[0], DOC_A[0])  # first in both rankings: 2 / (10 + 1)
        self.assertAlmostEqual(candidates[0]["fused_score"], 2 / 11, places=6)
        self.assertEqual(message["retrieval"]["context_count"], 3)
        spans = by_name(self.detail(run.pk)["spans"])
        self.assertEqual([child["name"] for child in spans["retrieve"]["children"]],
                         ["retrieve.load_indexes", "retrieve.embed_query", "retrieve.search", "retrieve.bm25",
                          "retrieve.fusion", "retrieve.select"])
        self.assertEqual(spans["retrieve.fusion"]["data"]["method"], "rrf")
        self.assertEqual(run.provenance["retrieval_parameters"]["fusion"], "rrf")
        self.assertEqual(run.provenance["retrieval_parameters"]["rrf_k"], 10)

    def test_hybrid_weight_one_and_zero_reproduce_dense_and_bm25_end_to_end(self):
        dense_message, _ = self.ask_with(None)
        bm25_message, _ = self.ask_with(self.make_pipeline(strategy="bm25"))
        as_dense, _ = self.ask_with(self.make_pipeline(strategy="hybrid", fusion="weighted", hybrid_weight=1))
        as_bm25, _ = self.ask_with(self.make_pipeline(strategy="hybrid", fusion="weighted", hybrid_weight=0))
        chunks = lambda message: [c["chunk_id"] for c in message["retrieval"]["candidates"]]  # noqa: E731
        self.assertEqual(chunks(as_dense), chunks(dense_message))
        self.assertEqual(chunks(as_bm25), chunks(bm25_message))


def predicting(scores=None, error=None):
    encoder = mock.Mock()
    if error is not None:
        encoder.predict.side_effect = error
    else:
        encoder.predict.side_effect = lambda pairs: np.asarray(scores[:len(pairs)], dtype=np.float32)
    return mock.patch("hybrid_rag.hybrid_rag.get_cross_encoder", return_value=encoder)


class RerankTurnTests(StrategyTestCase):
    def test_the_reranker_reorders_the_candidates_and_records_its_scores(self):
        pipeline = self.make_pipeline(strategy="hybrid_rerank", fusion="rrf", candidate_k=4, top_k=2,
                                 reranker={"provider": "ollama", "model": "nomic-embed-text"})
        with predicting([0.1, 0.2, 0.3, 0.9]) as factory:
            message, events = self.ask_with(pipeline)
        factory.assert_called_with("nomic-embed-text")
        candidates = message["retrieval"]["candidates"]
        self.assertEqual([c["retrieval_rank"] for c in candidates], [4, 3, 2, 1])
        self.assertEqual([c["rank"] for c in candidates], [1, 2, 3, 4])
        self.assertEqual([round(c["rerank_score"], 4) for c in candidates], [0.9, 0.3, 0.2, 0.1])
        # The context is the reranked top 2, and the evidence carries the rerank score.
        self.assertEqual([round(source["rerank_score"], 4) for source in message["citations"]], [0.9, 0.3])
        self.assertEqual(message["retrieval"]["context_count"], 2)
        self.assertEqual(message["retrieval"]["rerank"]["applied"], True)
        stage = [data for name, data in events if name == "stage" and data["id"] == "retrieve" and data["status"] == "completed"]
        self.assertIn("reranked to 2", stage[0]["detail"])

        texts, run = self.texts(message)
        self.assertIsNotNone(run.rerank_ms)
        detail = self.detail(run.pk)
        self.assertEqual(detail["latency_ms"]["rerank"], run.rerank_ms)
        stored = detail["candidates"]
        self.assertEqual([c["retrieval_rank"] for c in stored], [4, 3, 2, 1])
        self.assertEqual([c["selected_for_context"] for c in stored], [True, True, False, False])
        self.assertEqual([c["citation_id"] for c in stored], [1, 2, None, None])
        self.assertAlmostEqual(stored[0]["rerank_score"], 0.9, places=5)
        spans = by_name(detail["spans"])
        self.assertEqual(spans["retrieve"]["children"][-1]["name"], "retrieve.rerank")
        self.assertEqual((spans["retrieve.rerank"]["status"], spans["retrieve.rerank"]["data"]["provider"]), ("completed", "ollama"))
        self.assertEqual(detail["provenance"]["reranker"], {
            "provider": "ollama", "model": "nomic-embed-text", "applied": True, "fallback": False, "error_code": None,
        })

    def test_a_reranker_failure_keeps_the_fused_order_and_the_turn_completes(self):
        pipeline = self.make_pipeline(strategy="hybrid_rerank", fusion="rrf", candidate_k=4, top_k=2)
        with predicting(error=ConnectionError("ollama down")):
            message, events = self.ask_with(pipeline)
        self.assertEqual(message["status"], "complete")
        candidates = message["retrieval"]["candidates"]
        self.assertEqual([c["rank"] for c in candidates], [1, 2, 3, 4])
        self.assertEqual([c["retrieval_rank"] for c in candidates], [1, 2, 3, 4])
        self.assertTrue(all(c["rerank_score"] is None for c in candidates))
        self.assertEqual(message["retrieval"]["rerank"]["fallback"], True)
        texts, run = self.texts(message)
        self.assertEqual(run.status, "completed")
        detail = self.detail(run.pk)
        span = by_name(detail["spans"])["retrieve.rerank"]
        self.assertEqual((span["status"], span["error_code"]), ("fallback", "reranker_unavailable"))
        self.assertEqual(by_name(detail["spans"])["chat.turn"]["status"], "completed")
        self.assertEqual(detail["provenance"]["reranker"]["error_code"], "reranker_unavailable")
        self.assertTrue(detail["provenance"]["reranker"]["fallback"])

    def test_an_invalid_llm_reranker_reply_falls_back_too(self):
        pipeline = self.make_pipeline(strategy="hybrid_rerank", candidate_k=3, top_k=2,
                                 reranker={"provider": "llm", "model": "vendor/judge"})
        judge = mock.Mock()
        judge.generate.return_value = "I think passage 2 is best."
        with mock.patch.object(llms, "llm_for", return_value=judge):
            message, _ = self.ask_with(pipeline)
        self.assertEqual(message["status"], "complete")
        run = RetrievalRun.objects.get(pk=message["retrieval"]["run_id"])
        span = run.spans.get(name="retrieve.rerank")
        self.assertEqual((span.status, span.error_code), ("fallback", "reranker_invalid_response"))

    def test_the_llm_reranker_scores_reorder_the_context(self):
        pipeline = self.make_pipeline(strategy="hybrid_rerank", candidate_k=3, top_k=1,
                                 reranker={"provider": "llm", "model": "vendor/judge"})
        judge = mock.Mock()
        judge.generate.return_value = json.dumps({"scores": [{"id": 1, "score": 1}, {"id": 2, "score": 2}, {"id": 3, "score": 9}]})
        with mock.patch.object(llms, "llm_for", return_value=judge):
            message, _ = self.ask_with(pipeline)
        self.assertEqual([c["retrieval_rank"] for c in message["retrieval"]["candidates"]], [3, 2, 1])
        self.assertAlmostEqual(message["citations"][0]["rerank_score"], 0.9)
        self.assertIn("[3] ", judge.generate.call_args.args[0])

    def test_a_missing_reranker_key_falls_back(self):
        pipeline = self.make_pipeline(strategy="hybrid_rerank", candidate_k=3, top_k=1,
                                 reranker={"provider": "llm", "model": "vendor/judge"})
        with override_settings(OPENROUTER_API_KEY=""):
            message, _ = self.ask_with(pipeline)
        run = RetrievalRun.objects.get(pk=message["retrieval"]["run_id"])
        self.assertEqual(run.spans.get(name="retrieve.rerank").error_code, "missing_provider_key")


class GenerationModelTests(StrategyTestCase):
    def test_another_generation_model_answers_through_its_own_client_at_the_pipeline_temperature(self):
        pipeline = self.make_pipeline(generation_model="anthropic/claude-haiku-4.5", temperature=0.7)
        with override_settings(OPENROUTER_API_KEY="test-key"):
            other = OpenRouterLLM(model="anthropic/claude-haiku-4.5")
        chat = FakeChat(answer="Haiku says alpha [1].")
        chat.served_by = "anthropic/claude-haiku-4.5"
        other.client = SimpleNamespace(chat=SimpleNamespace(completions=chat))
        with mock.patch.object(llms, "llm_for", return_value=other) as factory:
            message, _ = self.ask_with(pipeline)
        factory.assert_called_with("anthropic/claude-haiku-4.5")
        self.assertEqual(message["content"], "Haiku says alpha [1].")
        self.assertEqual((chat.stream_calls[-1]["model"], chat.stream_calls[-1]["temperature"]), ("anthropic/claude-haiku-4.5", 0.7))
        self.assertEqual(self.chat.stream_calls, [])  # the engine's model did not answer
        self.assertEqual(message["retrieval"]["pipeline"]["generation_model"], "anthropic/claude-haiku-4.5")
        self.assertEqual(message["retrieval"]["pipeline"]["temperature"], 0.7)


class Phase1EquivalenceTests(StrategyTestCase):
    """The default pipeline ranks exactly as Phase 1's dense retrieval did."""

    @staticmethod
    def phase1(snapshots, query, candidate_k=20):
        """Phase 1's algorithm, verbatim (workspace/services/chat.py before Phase 3)."""
        query_vector = np.asarray(keyword_vector(query), dtype=np.float32)
        query_vector = query_vector / (np.linalg.norm(query_vector) or 1.0)
        pool = []
        for order, snap in enumerate(snapshots):
            scores = snap.matrix @ query_vector
            depth = min(candidate_k, len(scores))
            for index in np.argpartition(-scores, depth - 1)[:depth]:
                pool.append((float(scores[index]), order, int(index), snap))
        pool.sort(key=lambda item: (-item[0], item[1], item[2]))
        seen, kept = set(), []
        for item in pool:
            key = " ".join(item[3].texts[item[2]].split())
            if key in seen:
                continue
            seen.add(key)
            kept.append(item)
            if len(kept) == candidate_k:
                break
        return [(item[3].chunk_ids[item[2]], round(item[0], 6)) for item in kept]

    def test_default_pipeline_matches_the_phase1_ranking(self):
        third = self.ready_text_document("\n\n".join([DOC_A[0], "Epsilon and alpha share this passage now.", DOC_B[0]]), title="Overlap")
        from router.models import Document
        documents = list(Document.objects.filter(pk__in=[self.doc_a["id"], self.doc_b["id"], third["id"]]).order_by("created_at", "id"))
        snapshots = [index_cache.get_snapshot(self.pipeline, document.current_index, "openai/text-embedding-3-small") for document in documents]
        for question in (QUERY, "epsilon", "beta zeta", "radiation"):
            expected = self.phase1(snapshots, question)
            version = pipelines.latest_version(pipelines.default_pipeline_for(documents[0].workspace))
            found = retrieval.run_retrieval(question, documents, version.config, engine=self.pipeline)
            self.assertEqual([(c.chunk_id, round(c.retrieval_score, 6)) for c in found.candidates], expected, question)
            self.assertEqual(len(found.context), min(5, len(expected)))

    def test_an_embedding_model_other_than_the_index_model_is_refused(self):
        version = pipelines.latest_version(pipelines.default_pipeline_for(Workspace.objects.get(user=self.user)))
        with self.assertRaises(Exception) as caught:
            retrieval.run_retrieval(QUERY, [], {**version.config, "embedding_model": "other/model"}, engine=self.pipeline)
        self.assertEqual(caught.exception.code, "embedding_model_mismatch")


class LlmClientTests(SimpleTestCase):
    def test_one_shared_client_per_model_and_the_engine_llm_for_its_own_model(self):
        llms.clear()
        self.addCleanup(llms.clear)
        engine = SimpleNamespace(llm=SimpleNamespace(model="openai/gpt-4o-mini"))
        self.assertIs(llms.generation_llm(engine, "openai/gpt-4o-mini"), engine.llm)
        with override_settings(OPENROUTER_API_KEY="test-key"):
            first = llms.generation_llm(engine, "vendor/model-a")
            self.assertIs(llms.llm_for("vendor/model-a"), first)
            self.assertIsNot(llms.llm_for("vendor/model-b"), first)
        self.assertEqual(first.model, "vendor/model-a")


class RerankUnavailableCodeTests(SimpleTestCase):
    def test_ollama_errors_keep_their_code(self):
        self.assertEqual(retrieval._fallback_code(RerankUnavailable("x")), "reranker_unavailable")
        self.assertEqual(retrieval._fallback_code(ValueError("x")), "reranker_failed")
