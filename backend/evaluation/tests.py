"""
Tests for the evaluation app: retrieval metrics, LLM score parsing, and the
ground-truth evaluation endpoints.

Hermetic: no Redis, no network, no LLM keys. RAG_DISABLE_ENGINE_INIT is set
before the URLconf (and therefore rag.rag_service) is imported.
"""
import os
import tempfile
from unittest import mock

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from evaluation.eval import (
    calculate_precision_K,
    calculate_recall_K,
    calculate_f1_K,
    evaluate_chunks,
    evaluate_response,
    _parse_llm_score,
)
from evaluation.models import Chunk, GroundTruthChunk, GroundTruthResponse
from router.models import GuestUser, Document, Conversation, AnalysisBatch, AnalysisResult

TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="ragreader-test-media-")
LOCMEM_CACHE = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}


# ── Retrieval metrics ────────────────────────────────────────────────────────

class RetrievalMetricTests(TestCase):
    def test_precision_recall_f1(self):
        retrieved = {1, 2, 3}
        ground_truth = {2, 3, 4}
        self.assertAlmostEqual(calculate_precision_K(retrieved, ground_truth), 2 / 3)
        self.assertAlmostEqual(calculate_recall_K(retrieved, ground_truth), 2 / 3)
        self.assertAlmostEqual(calculate_f1_K(retrieved, ground_truth), 2 / 3)

    def test_empty_inputs(self):
        self.assertEqual(calculate_precision_K([], {1}), 0.0)
        self.assertEqual(calculate_recall_K({1}, []), 0.0)
        self.assertEqual(calculate_f1_K([], []), 0.0)

    def test_perfect_retrieval(self):
        scores = evaluate_chunks({1, 2}, {1, 2})
        self.assertEqual(scores["precision_k"], 1.0)
        self.assertEqual(scores["recall_k"], 1.0)
        self.assertEqual(scores["f1_k"], 1.0)

    def test_disjoint_retrieval(self):
        scores = evaluate_chunks({1}, {2})
        self.assertEqual(scores["precision_k"], 0.0)
        self.assertEqual(scores["recall_k"], 0.0)
        self.assertEqual(scores["f1_k"], 0.0)


# ── LLM score parsing ────────────────────────────────────────────────────────

class ParseLlmScoreTests(TestCase):
    def test_clean_json(self):
        raw = '{"faithfulness": 4, "justification": "grounded"}'
        self.assertAlmostEqual(_parse_llm_score(raw, "faithfulness"), 0.8)

    def test_json_wrapped_in_markdown_fences(self):
        raw = '```json\n{"relevance": 5, "justification": "spot on"}\n```'
        self.assertAlmostEqual(_parse_llm_score(raw, "relevance"), 1.0)

    def test_prose_fallback(self):
        self.assertAlmostEqual(_parse_llm_score("Score: 3 out of 5", "coverage"), 0.6)

    def test_error_text_never_becomes_a_score(self):
        # Regression: an API error string containing "401" used to parse as a
        # "score" of 401/5 = 80.4.
        raw = "OpenRouter Error (mistralai/mistral-nemo): Error code: 401 - Unauthorized"
        self.assertEqual(_parse_llm_score(raw, "faithfulness"), 0.0)

    def test_out_of_range_score_rejected(self):
        self.assertEqual(_parse_llm_score('{"coverage": 42}', "coverage"), 0.0)

    def test_empty_and_none(self):
        self.assertEqual(_parse_llm_score("", "coverage"), 0.0)
        self.assertEqual(_parse_llm_score(None, "coverage"), 0.0)


class EvaluateResponseTests(TestCase):
    def test_scores_with_mocked_judge(self):
        judge = mock.Mock()
        judge._call_api.return_value = (
            '{"faithfulness": 4, "relevance": 4, "coverage": 4}'
        )
        with mock.patch("evaluation.eval.MistralLLM", return_value=judge):
            scores = evaluate_response(
                "the sky is blue", "the sky is blue", chunks=["the sky is blue"]
            )
        self.assertGreater(scores["rougeL_f1"], 0.9)
        self.assertAlmostEqual(scores["faithfulness"], 0.8)
        self.assertAlmostEqual(scores["answer_relevance"], 0.8)
        self.assertAlmostEqual(scores["answer_coverage"], 0.8)

    def test_llm_failure_keeps_rouge_scores(self):
        # Regression: one failed judge call used to zero out the already
        # computed ROUGE scores as well.
        judge = mock.Mock()
        judge._call_api.side_effect = RuntimeError("OpenRouter down")
        with mock.patch("evaluation.eval.MistralLLM", return_value=judge):
            scores = evaluate_response("identical text", "identical text")
        self.assertGreater(scores["rougeL_f1"], 0.9)
        self.assertEqual(scores["faithfulness"], 0.0)


# ── Endpoints ────────────────────────────────────────────────────────────────

@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class ChunkEndpointTests(TestCase):
    def setUp(self):
        self.user = GuestUser.objects.create(username="alice", email="a@example.com")
        text_path = default_storage.save(
            "documents/user_alice/extracted.txt",
            ContentFile("First paragraph of the doc.\n\nSecond paragraph of the doc."),
        )
        self.document = Document.objects.create(
            user=self.user,
            name="doc",
            source_type="text",
            extracted_text_path=text_path,
        )

    def test_create_chunks(self):
        resp = self.client.post(
            "/api/v1/chunk/",
            {"USER": "alice"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(Chunk.objects.filter(document=self.document).count(), 0)

    def test_get_chunks(self):
        Chunk.objects.create(document=self.document, text="chunk one")
        resp = self.client.get(f"/api/v1/chunk/{self.document.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["chunks"]), 1)

    def test_create_chunks_unknown_user_404(self):
        resp = self.client.post(
            "/api/v1/chunk/",
            {"USER": "ghost"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class GroundTruthEndpointTests(TestCase):
    def setUp(self):
        self.user = GuestUser.objects.create(username="alice", email="a@example.com")
        self.document = Document.objects.create(
            user=self.user, name="doc", source_type="text"
        )
        self.conversation = Conversation.objects.create(
            user=self.user, query="q", response="r", context="c"
        )
        self.chunk = Chunk.objects.create(document=self.document, text="chunk text")

    def test_create_ground_truth_chunk(self):
        resp = self.client.post(
            "/api/v1/ground-truth-chunk/",
            {"conversation_id": self.conversation.id, "chunk_id": [self.chunk.id]},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            GroundTruthChunk.objects.filter(conversation=self.conversation).exists()
        )

    def test_create_ground_truth_chunk_unknown_conversation(self):
        resp = self.client.post(
            "/api/v1/ground-truth-chunk/",
            {"conversation_id": 424242, "chunk_id": [self.chunk.id]},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_get_ground_truth_chunks(self):
        GroundTruthChunk.objects.create(
            conversation=self.conversation, chunk=self.chunk
        )
        resp = self.client.get(f"/api/v1/ground-truth-chunk/{self.conversation.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["ground_truth_chunks"]), 1)

    def test_create_and_get_ground_truth_response(self):
        resp = self.client.post(
            "/api/v1/ground-truth-response/",
            {"conversation_id": self.conversation.id, "response": "truth"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(
            f"/api/v1/ground-truth-response/{self.conversation.id}/"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json()["ground_truth_responses"][0]["response"], "truth"
        )


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class GroundTruthChunkEvaluationTests(TestCase):
    def setUp(self):
        self.user = GuestUser.objects.create(username="alice", email="a@example.com")
        self.document = Document.objects.create(
            user=self.user, name="doc", source_type="text"
        )
        self.conversation = Conversation.objects.create(
            user=self.user, query="q", response="r", context="c"
        )
        self.chunks = [
            Chunk.objects.create(document=self.document, text=f"chunk {i}")
            for i in range(3)
        ]
        for chunk in self.chunks[:2]:
            GroundTruthChunk.objects.create(
                conversation=self.conversation, chunk=chunk
            )
        self.batch = AnalysisBatch.objects.create(user=self.user, query="q")
        AnalysisResult.objects.create(
            batch=self.batch,
            method="Dense Retrieval",
            ai_model="openai/gpt-4o-mini",
            answer="a",
            retrieved_chunks=[
                {"id": self.chunks[0].id, "text": "chunk 0", "score": 0.9},
                {"id": self.chunks[2].id, "text": "chunk 2", "score": 0.5},
            ],
            evaluation_metrics=[],
        )

    def test_evaluation_scores_are_computed_and_stored(self):
        resp = self.client.post(
            "/api/v1/evaluate/ground-truth-chunk/",
            {
                "conversation_id": self.conversation.id,
                "batch_id": str(self.batch.job_id),
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        evaluation = resp.json()["evaluations"][0]
        # 1 of 2 retrieved is relevant; 1 of 2 ground-truth found
        self.assertAlmostEqual(evaluation["scores"]["precision_k"], 0.5)
        self.assertAlmostEqual(evaluation["scores"]["recall_k"], 0.5)
        result = AnalysisResult.objects.get(batch=self.batch)
        self.assertTrue(
            any(m.get("name") == "ground_truth_eval" for m in result.evaluation_metrics)
        )

    def test_missing_params_400(self):
        resp = self.client.post(
            "/api/v1/evaluate/ground-truth-chunk/",
            {},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class GroundTruthResponseEvaluationTests(TestCase):
    def setUp(self):
        self.user = GuestUser.objects.create(username="alice", email="a@example.com")
        self.conversation = Conversation.objects.create(
            user=self.user, query="q", response="r", context="c"
        )

    def test_missing_params_400(self):
        resp = self.client.post(
            "/api/v1/evaluate/ground-truth-response/",
            {},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_no_ground_truth_404(self):
        resp = self.client.post(
            "/api/v1/evaluate/ground-truth-response/",
            {"conversation_id": self.conversation.id, "response": "answer"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_evaluates_against_ground_truth(self):
        # Regression: this endpoint used to be an empty `pass` and returned a
        # 500 for every request.
        GroundTruthResponse.objects.create(
            conversation=self.conversation, response="the truth"
        )
        fake_scores = {
            "rougeL_precision": 1.0,
            "rougeL_recall": 1.0,
            "rougeL_f1": 1.0,
            "faithfulness": 0.8,
            "answer_relevance": 0.8,
            "answer_coverage": 0.8,
        }
        with mock.patch(
            "evaluation.views.evaluate_response", return_value=fake_scores
        ) as evaluator:
            resp = self.client.post(
                "/api/v1/evaluate/ground-truth-response/",
                {"conversation_id": self.conversation.id, "response": "the truth"},
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["scores"], fake_scores)
        evaluator.assert_called_once_with("the truth", "the truth")
