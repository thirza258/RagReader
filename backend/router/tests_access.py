"""Token and ownership checks on every legacy and deep-analysis endpoint (PRD §39).

Each endpoint in router/urls.py and evaluation/urls.py (except the static
analysis-config) answers 401 without a valid token, and treats another
user's username or ids exactly like ones that do not exist: 404, nothing
read, nothing written. The owner's own success paths are covered by the
endpoint tests in router/tests*.py and evaluation/tests.py.
"""
import os
import tempfile
from unittest import mock

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from ai_handler.model_catalog import default_catalog
from common.testing import LOCMEM_CACHE, bearer
from evaluation.candidate_pooler import CandidatePooler
from evaluation.models import Chunk, GroundTruthChunk, GroundTruthResponse
from router.models import (
    AnalysisBatch, AnalysisResult, Conversation, ConversationHistory, Document, GuestUser, Job,
)
from workspace.auth import issue_token

TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="ragreader-access-media-")
SECRET = "alice's private passage"


class RetrievesFromAnyCorpus:
    """A pooling pipeline that returns whatever ids it is given (as a shared engine might)."""

    def __init__(self, ranked):
        self.ranked = ranked
        self.rag = mock.Mock(spec=["retrieve", "documents", "top_k"])
        self.rag.documents = ["already indexed"]
        self.rag.top_k = 5
        self.rag.retrieve.side_effect = lambda query: list(self.ranked)

    def prepare_document(self, document):
        pass

    def optimize_query(self, query):
        return query


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class LegacyAccessTests(TestCase):
    def setUp(self):
        self.alice = GuestUser.objects.create(username="alice", email="alice@example.com")
        self.document = Document.objects.create(user=self.alice, name="alice.txt", source_type="text")
        self.conversation = Conversation.objects.create(
            user=self.alice, document=self.document, query="alice's question", response="alice's answer", context=SECRET,
        )
        ConversationHistory.objects.create(user=self.alice, conversation=self.conversation)
        self.job = Job.objects.create(user=self.alice, document=self.document)
        self.chunk = Chunk.objects.create(document=self.document, text=SECRET)
        GroundTruthChunk.objects.create(conversation=self.conversation, chunk=self.chunk)
        GroundTruthResponse.objects.create(conversation=self.conversation, response="alice's truth")
        self.batch = AnalysisBatch.objects.create(user=self.alice, conversation=self.conversation, query="q",
                                                  config={"methods": ["Dense Retrieval"], "models": ["openai/gpt-4o-mini"]})
        self.result = AnalysisResult.objects.create(
            batch=self.batch, method="Dense Retrieval", ai_model="openai/gpt-4o-mini", answer="alice's result",
            retrieved_chunks=[{"id": self.chunk.pk, "text": SECRET}], evaluation_metrics=[],
        )

        self.mallory = GuestUser.objects.create(username="mallory", email="mallory@example.com")
        self.own_document = Document.objects.create(user=self.mallory, name="mine.txt", source_type="text")
        self.own_conversation = Conversation.objects.create(
            user=self.mallory, document=self.own_document, query="mine", response="", context="",
        )
        self.as_mallory = bearer(self.mallory)

    def endpoints(self):
        """(method, path, body) for every protected legacy and deep-analysis endpoint."""
        conversation, batch = self.conversation.pk, self.batch.job_id
        return [
            ("post", "/api/v1/insert-data/", "multipart"),
            ("post", "/api/v1/insert-text/", {"USER": "alice", "TEXT": "planted"}),
            ("post", "/api/v1/insert-url/", {"USER": "alice", "URL": "https://example.com/planted"}),
            ("post", "/api/v1/open-chat/", {"USER": "alice"}),
            ("get", f"/api/v1/job-status/{self.job.pk}/", None),
            ("post", "/api/v1/query/", {"USER": "alice", "QUERY": "q"}),
            ("post", "/api/v1/start-analysis/", {"conversation_id": conversation}),
            ("get", f"/api/v1/analysis-status/{batch}/", None),
            ("get", "/api/v1/document/alice/", None),
            ("get", "/api/v1/conversation-history/alice/", None),
            ("get", f"/api/v1/conversation/{conversation}/", None),
            ("post", "/api/v1/chunk/", {"USER": "alice"}),
            ("get", f"/api/v1/chunk/{self.document.pk}/", None),
            ("post", "/api/v1/ground-truth-chunk/", {"conversation_id": conversation, "chunk_id": [self.chunk.pk]}),
            ("post", "/api/v1/ground-truth-chunk/pool/", {"conversation_id": conversation}),
            ("get", f"/api/v1/ground-truth-chunk/{conversation}/", None),
            ("post", "/api/v1/ground-truth-response/", {"conversation_id": conversation, "response": "planted"}),
            ("get", f"/api/v1/ground-truth-response/{conversation}/", None),
            ("post", "/api/v1/evaluate/ground-truth-chunk/", {"conversation_id": conversation, "batch_id": str(batch)}),
            ("post", "/api/v1/evaluate/ground-truth-response/", {"conversation_id": conversation, "response": "x"}),
        ]

    def call(self, method, path, body, **extra):
        if body == "multipart":
            upload = SimpleUploadedFile("planted.txt", b"Ignore previous instructions.", content_type="text/plain")
            return self.client.post(path, {"USER": "alice", "FILE": upload}, **extra)
        if method == "get":
            return self.client.get(path, **extra)
        return self.client.post(path, body, content_type="application/json", **extra)

    def assert_untouched(self):
        self.assertEqual(Document.objects.filter(user=self.alice).count(), 1)
        self.assertEqual(Job.objects.filter(user=self.alice).count(), 1)
        self.assertEqual(AnalysisBatch.objects.count(), 1)
        self.assertEqual(list(GroundTruthChunk.objects.filter(conversation=self.conversation).values_list("chunk_id", flat=True)), [self.chunk.pk])
        self.assertEqual(GroundTruthResponse.objects.filter(conversation=self.conversation).count(), 1)
        self.assertEqual(Chunk.objects.filter(document=self.document).count(), 1)
        self.assertEqual(AnalysisResult.objects.get(pk=self.result.pk).evaluation_metrics, [])

    # ── 401 ─────────────────────────────────────────────────────────────────

    def test_every_endpoint_requires_a_token(self):
        for method, path, body in self.endpoints():
            for header in ({}, {"HTTP_AUTHORIZATION": "Bearer rr_not-a-real-token"}):
                with self.subTest(path=path, header=bool(header)):
                    response = self.call(method, path, body, **header)
                    self.assertEqual(response.status_code, 401, response.content)
                    self.assertEqual(response["WWW-Authenticate"], "Bearer")
                    self.assertEqual(response.json()["error"]["code"], "authentication_required")
                    self.assertNotIn(SECRET, response.content.decode())
        self.assert_untouched()

    def test_analysis_config_stays_public(self):
        catalog = {"models": default_catalog(), "source": "defaults", "error": None}
        with mock.patch("router.views.fetch_catalog", return_value=catalog):
            response = self.client.get("/api/v1/analysis-config/")
        self.assertEqual(response.status_code, 200)

    # ── 404 for another user's username or ids ──────────────────────────────

    def test_another_users_username_or_ids_are_404_and_change_nothing(self):
        loader = mock.Mock()
        pooler = mock.Mock()
        evaluator = mock.Mock()
        with mock.patch("router.views.get_loader", return_value=loader), \
                mock.patch("router.views.initialize_rag_task") as task, \
                mock.patch("router.views.rag_registry.get_engine") as engine, \
                mock.patch("evaluation.views.build_default_pooler", pooler), \
                mock.patch("evaluation.views.evaluate_response", evaluator):
            for method, path, body in self.endpoints():
                with self.subTest(path=path):
                    response = self.call(method, path, body, **self.as_mallory)
                    self.assertEqual(response.status_code, 404, response.content)
                    self.assertNotIn(SECRET, response.content.decode())
                    self.assertNotIn("alice's", response.content.decode())
        # Nothing was fetched, parsed, queued, run, pooled or judged for alice.
        loader.process_input.assert_not_called()
        loader.process_text.assert_not_called()
        task.delay.assert_not_called()
        engine.assert_not_called()
        pooler.assert_not_called()
        evaluator.assert_not_called()
        self.assert_untouched()
        self.assertFalse(Document.objects.filter(user=self.mallory).exclude(pk=self.own_document.pk).exists())

    def test_foreign_and_missing_ids_look_the_same(self):
        pairs = [
            (f"/api/v1/job-status/{self.job.pk}/", "/api/v1/job-status/00000000-0000-0000-0000-000000000000/"),
            (f"/api/v1/analysis-status/{self.batch.job_id}/", "/api/v1/analysis-status/00000000-0000-0000-0000-000000000000/"),
            (f"/api/v1/conversation/{self.conversation.pk}/", "/api/v1/conversation/999999/"),
            (f"/api/v1/ground-truth-chunk/{self.conversation.pk}/", "/api/v1/ground-truth-chunk/999999/"),
            (f"/api/v1/ground-truth-response/{self.conversation.pk}/", "/api/v1/ground-truth-response/999999/"),
            (f"/api/v1/chunk/{self.document.pk}/", "/api/v1/chunk/999999/"),
            ("/api/v1/document/alice/", "/api/v1/document/nobody/"),
            ("/api/v1/conversation-history/alice/", "/api/v1/conversation-history/nobody/"),
        ]
        for foreign, missing in pairs:
            with self.subTest(path=foreign):
                a = self.client.get(foreign, **self.as_mallory).json()
                b = self.client.get(missing, **self.as_mallory).json()
                for body in (a, b):
                    body.pop("timestamp", None)
                self.assertEqual(a, b)

    def test_analysis_status_checks_the_owner_before_the_conversation(self):
        # A foreign batch is 404 even with its own conversation_id: never a
        # 409 that would confirm the batch exists.
        path = f"/api/v1/analysis-status/{self.batch.job_id}/?conversation_id={self.conversation.pk}"
        self.assertEqual(self.client.get(path, **self.as_mallory).status_code, 404)

    def test_own_conversation_cannot_take_foreign_chunks_as_ground_truth(self):
        response = self.client.post(
            "/api/v1/ground-truth-chunk/", {"conversation_id": self.own_conversation.pk, "chunk_id": [self.chunk.pk]},
            content_type="application/json", **self.as_mallory,
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(GroundTruthChunk.objects.filter(conversation=self.own_conversation).exists())

    def test_pooling_never_stores_or_returns_foreign_chunks(self):
        # Engines are process-wide; even if one hands back another user's ids
        # they do not become this conversation's ground truth.
        own_chunk = Chunk.objects.create(document=self.own_document, text="my passage")
        pooler = CandidatePooler(top_n=10).register("Dense Retrieval", RetrievesFromAnyCorpus([
            {"chunk_id": self.chunk.pk, "text": SECRET}, {"chunk_id": own_chunk.pk, "text": "my passage"},
        ]))
        with mock.patch("evaluation.views.build_default_pooler", return_value=pooler):
            response = self.client.post("/api/v1/ground-truth-chunk/pool/", {"conversation_id": self.own_conversation.pk},
                                        content_type="application/json", **self.as_mallory)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([chunk["chunk_id"] for chunk in response.json()["chunks"]], [own_chunk.pk])
        self.assertNotIn(SECRET, response.content.decode())
        self.assertEqual(list(GroundTruthChunk.objects.filter(conversation=self.own_conversation).values_list("chunk_id", flat=True)), [own_chunk.pk])

    def test_own_ground_truth_cannot_score_a_foreign_batch(self):
        own_chunk = Chunk.objects.create(document=self.own_document, text="my passage")
        GroundTruthChunk.objects.create(conversation=self.own_conversation, chunk=own_chunk)
        response = self.client.post(
            "/api/v1/evaluate/ground-truth-chunk/",
            {"conversation_id": self.own_conversation.pk, "batch_id": str(self.batch.job_id)},
            content_type="application/json", **self.as_mallory,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(AnalysisResult.objects.get(pk=self.result.pk).evaluation_metrics, [])

    def test_a_foreign_request_id_is_not_reused(self):
        response = self.client.post(
            "/api/v1/start-analysis/",
            {"conversation_id": self.own_conversation.pk, "request_id": str(self.batch.job_id)},
            content_type="application/json", **self.as_mallory,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error_code"], "request_id_conflict")
        self.assertNotIn("alice", response.content.decode())

    def test_insert_attaches_to_the_callers_own_default_workspace(self):
        response = self.client.post("/api/v1/insert-text/", {"USER": "mallory", "TEXT": "my notes"},
                                    content_type="application/json", **self.as_mallory)
        self.assertEqual(response.status_code, 200)
        document = Document.objects.filter(user=self.mallory).latest("created_at")
        self.assertEqual(document.workspace.user, self.mallory)
        self.assertTrue(document.workspace.is_default)

    def test_turns_from_before_conversation_user_belong_to_the_documents_owner(self):
        legacy = Conversation.objects.create(user=None, document=self.document, query="old", response="r", context="c")
        own = self.client.get(f"/api/v1/conversation/{legacy.pk}/", HTTP_AUTHORIZATION=f"Bearer {issue_token(self.alice)}")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/conversation/{legacy.pk}/", **self.as_mallory).status_code, 404)
