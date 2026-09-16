"""Regressions for stable job identity, embedding alignment and durable errors."""
import json
import pickle
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

import httpx
import numpy as np
from django.db import IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from openai import OpenAI

from common.embeddings import embed_texts
from common.errors import PipelineError
from dense_rag.dense_rag import DenseRAG
from evaluation.models import Chunk
from pipeline.dense_rag_pipeline import DenseRAGPipeline
from pipeline.hybrid_rag_pipeline import HybridRAGPipeline
from router.analysis import claim_batch, release_batch, renew_batch, save_variant
from router.models import AnalysisBatch, AnalysisResult, Conversation, Document, DocumentVector, GuestUser, Job
from router.tasks import initialize_rag_task
from router.tests_pipeline import PipelineTestCase, make_document, make_user, TEST_MEDIA_ROOT

CONFIG = {"methods": ["Dense Retrieval"], "models": ["openai/gpt-4o-mini"]}


class EmbeddingResponseTests(SimpleTestCase):
    def provider_client(self, handler):
        client = OpenAI(api_key="fixture", base_url="https://openrouter.ai/api/v1", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        self.addCleanup(client.close)
        return client

    def test_batches_and_reorders_vectors_using_the_provider_input_index(self):
        requests = []
        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            rows = [{"object": "embedding", "index": i, "embedding": [float(text), 1.0]}
                    for i, text in enumerate(body["input"])]
            return httpx.Response(200, json={"object": "list", "model": body["model"], "data": rows[::-1], "usage": {"prompt_tokens": 1, "total_tokens": 1}})
        vectors = embed_texts(self.provider_client(handler), [str(i) for i in range(130)], "openai/test-embedding")
        self.assertEqual([len(r["input"]) for r in requests], [64, 64, 2])
        self.assertEqual(vectors, [[float(i), 1.0] for i in range(130)])
        self.assertEqual({r["model"] for r in requests}, {"openai/test-embedding"})

    def test_invalid_responses_are_errors_instead_of_misaligned_indexes(self):
        for rows in ([], [SimpleNamespace(index=0, embedding=[1, 0])] * 2,
                     [SimpleNamespace(index=0, embedding=[float("nan"), 1]), SimpleNamespace(index=1, embedding=[1, 0])],
                     [SimpleNamespace(index=0, embedding=[1, 0]), SimpleNamespace(index=1, embedding=[1])],
                     [SimpleNamespace(index=0, embedding=[0, 0]), SimpleNamespace(index=1, embedding=[1, 0])],
                     [SimpleNamespace(index=0, embedding=[1e308, 1e308]), SimpleNamespace(index=1, embedding=[1, 0])],
                     [SimpleNamespace(embedding=[1, 0]), SimpleNamespace(index=1, embedding=[1, 0])]):
            with self.subTest(rows=rows):
                client = mock.Mock()
                client.embeddings.create.return_value = SimpleNamespace(data=rows)
                with self.assertRaises(PipelineError) as raised:
                    embed_texts(client, ["first", "second"], "embedding")
                self.assertEqual(raised.exception.code, "invalid_embeddings")

    def test_provider_errors_have_stable_codes_without_raw_response_bodies(self):
        for status, code, retryable in ((401, "provider_authentication", False), (402, "provider_credits", False),
                                        (429, "provider_rate_limit", True), (503, "provider_unavailable", True),
                                        (400, "provider_request_rejected", False)):
            with self.subTest(status=status):
                client = self.provider_client(lambda request: httpx.Response(status, json={"error": {"message": "PRIVATE PROVIDER BODY"}}))
                with self.assertRaises(PipelineError) as raised:
                    embed_texts(client, ["document"], "embedding")
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(raised.exception.retryable, retryable)
                self.assertNotIn("PRIVATE", str(raised.exception))

    def test_timeout_is_reported_and_empty_input_does_not_call_provider(self):
        def timeout(request):
            raise httpx.ReadTimeout("PRIVATE", request=request)
        with self.assertRaises(PipelineError) as raised:
            embed_texts(self.provider_client(timeout), ["document"], "embedding")
        self.assertEqual(raised.exception.code, "provider_timeout")
        client = mock.Mock()
        with self.assertRaises(PipelineError) as raised:
            embed_texts(client, ["   "], "embedding")
        self.assertEqual(raised.exception.code, "empty_embedding_input")
        client.embeddings.create.assert_not_called()

    @override_settings(OPENROUTER_API_KEY="fixture")
    def test_failed_reindex_retains_old_text_ids_and_vectors(self):
        rag = DenseRAG({})
        self.addCleanup(rag.client.close)
        rag._get_embeddings = mock.Mock(return_value=[[1, 0]])
        rag.index_documents([{"text": "original", "chunk_id": 10}])
        before = rag.document_vectors.copy()
        rag._get_embeddings.side_effect = PipelineError("provider_timeout", "Timed out", retryable=True)
        with self.assertRaises(PipelineError):
            rag.index_documents([{"text": "replacement", "chunk_id": 20}])
        self.assertEqual(rag.documents, ["original"])
        self.assertEqual(rag.document_metadata, [{"chunk_id": 10}])
        np.testing.assert_array_equal(rag.document_vectors, before)

    @override_settings(OPENROUTER_API_KEY="fixture")
    def test_query_dimension_mismatch_is_a_clear_error(self):
        rag = DenseRAG({})
        self.addCleanup(rag.client.close)
        rag._get_embeddings = mock.Mock(return_value=[[1, 0]])
        rag.index_documents([{"text": "original", "chunk_id": 10}])
        rag._get_embeddings.return_value = [[1, 0, 0]]
        with self.assertRaises(PipelineError) as raised:
            rag.retrieve("question")
        self.assertEqual(raised.exception.code, "invalid_embeddings")

    def test_ollama_invalid_vectors_are_a_public_reranker_error(self):
        from hybrid_rag.hybrid_rag import OllamaCrossEncoder
        encoder = OllamaCrossEncoder("bge-m3")
        encoder._client = mock.Mock()
        encoder._client.embed.return_value = {"embeddings": [[float("nan"), 1]]}
        with self.assertRaises(PipelineError) as raised:
            encoder.predict([("question", "document")])
        self.assertEqual(raised.exception.code, "reranker_unavailable")
        self.assertIn("bge-m3", str(raised.exception))


class JobIdentityTests(TestCase):
    def setUp(self):
        self.user = GuestUser.objects.create(username="stable", email="stable@example.com")
        self.document = Document.objects.create(user=self.user, name="doc", source_type="text")
        self.conversation = Conversation.objects.create(user=self.user, document=self.document, query="question", response="answer", context="")

    def start(self, **payload):
        return self.client.post("/api/v1/start-analysis/", {"conversation_id": self.conversation.pk, "config": CONFIG, **payload}, content_type="application/json")

    def test_repeated_analysis_post_reuses_canonical_request_id(self):
        request_id = uuid4()
        first = self.start(request_id=request_id.hex.upper())
        second = self.start(request_id=str(request_id))
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["batch_id"], str(request_id))
        self.assertEqual(second.json()["batch_id"], str(request_id))
        self.assertEqual(AnalysisBatch.objects.count(), 1)
        conflict = self.start(request_id=str(request_id), config={**CONFIG, "top_k": 9})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error_code"], "request_id_conflict")

    def test_invalid_and_unknown_ids_have_explicit_http_errors(self):
        for endpoint in ("job-status", "analysis-status"):
            for value, status, code in (("invalid", 400, "invalid_job_id"), (str(uuid4()), 404, "job_not_found")):
                response = self.client.get(f"/api/v1/{endpoint}/{value}/")
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error_code"], code)
        response = self.start(request_id="invalid")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "invalid_request_id")

    def test_empty_chat_query_returns_validation_error(self):
        response = self.client.post("/api/v1/query/", {"USER": self.user.username, "QUERY": ""}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "invalid_request")

    def test_batch_cannot_be_loaded_under_another_conversation(self):
        batch_id = self.start().json()["batch_id"]
        response = self.client.get(f"/api/v1/analysis-status/{batch_id}/?conversation_id=999")
        self.assertEqual(response.status_code, 409)

    def test_open_chat_reuses_job_until_explicit_retry_of_a_failure(self):
        def post(**extra):
            with self.captureOnCommitCallbacks(execute=True):
                return self.client.post("/api/v1/open-chat/", {"USER": self.user.username, **extra}, content_type="application/json")
        with mock.patch("router.views.initialize_rag_task.delay") as enqueue:
            first = post().json()["data"]
            self.assertEqual(post().json()["data"]["job_id"], first["job_id"])
            job = Job.objects.get(pk=first["job_id"])
            job.mark_failed("Embedding timed out", "provider_timeout", True)
            self.assertEqual(post().json()["data"]["job_id"], first["job_id"])
            retried = post(retry=True).json()["data"]
            self.assertNotEqual(retried["job_id"], first["job_id"])
            self.assertEqual(retried["document_id"], self.document.pk)
            self.assertEqual(enqueue.call_count, 2)

    def test_initialization_uses_job_owner_and_does_not_repeat_deliveries(self):
        job = Job.objects.create(user=self.user, document=self.document)
        engine = mock.Mock()
        with mock.patch("router.tasks.rag_registry.get_engine", return_value=engine):
            self.assertTrue(initialize_rag_task(str(job.pk), "stale-username", "Dense Retrieval", "openai/gpt-4o-mini"))
            self.assertTrue(initialize_rag_task(str(job.pk), "stale-username", "Dense Retrieval", "openai/gpt-4o-mini"))
        engine.init_job.assert_called_once()
        self.assertEqual(engine.init_job.call_args.args, (self.user.username,))
        self.assertEqual(engine.init_job.call_args.kwargs["job"].document_id, self.document.pk)

    def test_initialization_embedding_error_is_returned_by_status_and_chat(self):
        job = Job.objects.create(user=self.user, document=self.document)
        engine = mock.Mock()
        engine.init_job.side_effect = PipelineError("provider_timeout", "Embedding timed out. Try again.", retryable=True, http_status=504)
        with mock.patch("router.tasks.rag_registry.get_engine", return_value=engine):
            self.assertFalse(initialize_rag_task(str(job.pk), self.user.username, "Dense Retrieval", "openai/gpt-4o-mini"))
        status = self.client.get(f"/api/v1/job-status/{job.pk}/").json()["data"]
        self.assertEqual(status["status"], "FAILED")
        self.assertEqual(status["error_code"], "provider_timeout")
        response = self.client.post("/api/v1/query/", {"USER": self.user.username, "QUERY": "question"}, content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], status["error"])
        self.assertTrue(response.json()["retryable"])

    def test_stalled_worker_is_a_terminal_error_instead_of_polling_forever(self):
        job = Job.objects.create(user=self.user, document=self.document, status=Job.Status.PROCESSING)
        Job.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=36))
        payload = self.client.get(f"/api/v1/job-status/{job.pk}/").json()["data"]
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["error_code"], "initialization_timeout")

    def test_saved_failure_is_terminal_and_never_unlocks_modules(self):
        batch = AnalysisBatch.objects.get(job_id=self.start().json()["batch_id"])
        save_variant(batch, CONFIG["methods"][0], CONFIG["models"][0], error={"error": "Embedding failed", "error_code": "provider_timeout", "retryable": True})
        payload = self.client.get(f"/api/v1/analysis-status/{batch.job_id}/").json()
        self.assertTrue(payload["is_finished"])
        self.assertFalse(payload["is_complete"])
        self.assertEqual((payload["completed"], payload["failed"]), (0, 1))
        self.assertFalse(payload["modules_available"])
        self.assertEqual(payload["results"][0]["error_code"], "provider_timeout")

    def test_lease_blocks_duplicates_and_fences_stale_workers(self):
        batch = AnalysisBatch.objects.get(job_id=self.start().json()["batch_id"])
        first, second = uuid4(), uuid4()
        self.assertTrue(claim_batch(batch.pk, first))
        self.assertFalse(claim_batch(batch.pk, second))
        AnalysisBatch.objects.filter(pk=batch.pk).update(execution_updated_at=timezone.now() - timedelta(minutes=3))
        self.assertTrue(claim_batch(batch.pk, second))
        self.assertFalse(renew_batch(batch.pk, first))
        release_batch(batch.pk, first)
        with self.assertRaises(PipelineError) as raised:
            save_variant(batch, CONFIG["methods"][0], CONFIG["models"][0], response={"answer": "stale"}, token=first)
        self.assertEqual(raised.exception.code, "analysis_lease_lost")
        save_variant(batch, CONFIG["methods"][0], CONFIG["models"][0], response={"answer": "current"}, token=second)
        self.assertEqual(batch.results.get().answer, "current")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class IndexStabilityTests(PipelineTestCase):
    def test_incomplete_hybrid_cache_never_combines_with_previous_document(self):
        user = make_user()
        document = make_document(user)
        pipeline = self.make_pipeline(HybridRAGPipeline)
        path = pipeline._build_index(user.username, document)
        old_sparse, old_dense = pipeline.rag.sparse_engine, pipeline.rag.dense_engine
        with open(path, "rb") as handle:
            state = pickle.load(handle)
        del state["dense"]
        with open(path, "wb") as handle:
            pickle.dump(state, handle)
        self.assertFalse(pipeline._load_state(path))
        self.assertIs(pipeline.rag.sparse_engine, old_sparse)
        self.assertIs(pipeline.rag.dense_engine, old_dense)

    def test_baseline_analysis_reloads_the_exact_document_from_its_conversation(self):
        user = make_user()
        first = make_document(user)
        second = make_document(user, text="Different document beta", name="second")
        conversation = Conversation.objects.create(user=user, document=first, query="alpha", response="", context="")
        for cls in (DenseRAGPipeline, HybridRAGPipeline):
            with self.subTest(pipeline=cls.__name__):
                pipeline = self.make_pipeline(cls)
                pipeline.prepare_document(second)
                with mock.patch.object(pipeline, "_run_core", return_value={"answer": "ok", "context": [], "chunk_ids": []}):
                    pipeline.run_analysis(first.pk, conversation.pk)
                rag = pipeline.rag.dense_engine if cls is HybridRAGPipeline else pipeline.rag
                self.assertTrue(all(Chunk.objects.get(pk=meta["chunk_id"]).document_id == first.pk for meta in rag.document_metadata))
                self.assertNotIn("Different document beta", rag.documents)

    def test_job_indexes_its_original_document_after_a_new_upload(self):
        user = make_user()
        first = make_document(user)
        job = Job.objects.create(user=user, document=first)
        make_document(user, text="Later uploaded beta", name="later")
        pipeline = self.make_pipeline(DenseRAGPipeline)
        pipeline.init_job(user.username, job=job)
        self.assertTrue(DocumentVector.objects.filter(document=first).exists())
        self.assertNotIn("Later uploaded beta", pipeline.rag.documents)

    def test_failed_embedding_rolls_back_chunk_changes_and_keeps_both_hybrid_indexes(self):
        user = make_user()
        document = make_document(user)
        pipeline = self.make_pipeline(HybridRAGPipeline)
        pipeline.prepare_document(document)
        old_chunks = list(Chunk.objects.filter(document=document).values_list("id", "text"))
        old_sparse, old_dense = pipeline.rag.sparse_engine, pipeline.rag.dense_engine
        pipeline.chunker.chunk = mock.Mock(return_value=["New chunk to embed"])
        with mock.patch.object(old_dense, "_get_embeddings", side_effect=PipelineError("provider_timeout", "Embedding timed out")):
            with self.assertRaises(PipelineError):
                pipeline._build_index(user.username, document)
        self.assertEqual(list(Chunk.objects.filter(document=document).values_list("id", "text")), old_chunks)
        self.assertIs(pipeline.rag.sparse_engine, old_sparse)
        self.assertIs(pipeline.rag.dense_engine, old_dense)
        self.assertEqual(DocumentVector.objects.filter(document=document).count(), 1)


class QueueFailureTests(TransactionTestCase):
    def test_concurrent_open_chat_requests_share_one_job(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.test import Client
        from django.db import close_old_connections
        user = GuestUser.objects.create(username="concurrent", email="concurrent@example.com")
        Document.objects.create(user=user, name="doc", source_type="text")
        def post():
            close_old_connections()
            try:
                response = Client().post("/api/v1/open-chat/", {"USER": user.username}, content_type="application/json")
                self.assertIn(response.status_code, (200, 202))
                return response.json()["data"]["job_id"]
            finally:
                close_old_connections()
        with mock.patch("router.views.initialize_rag_task.delay") as enqueue, ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: post(), range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(Job.objects.count(), 1)
        enqueue.assert_called_once()

    def test_unreachable_worker_returns_job_id_and_durable_failure(self):
        user = GuestUser.objects.create(username="queue", email="queue@example.com")
        Document.objects.create(user=user, name="doc", source_type="text")
        with mock.patch("router.views.initialize_rag_task.delay", side_effect=ConnectionError("PRIVATE")):
            response = self.client.post("/api/v1/open-chat/", {"USER": "queue"}, content_type="application/json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error_code"], "job_queue_unavailable")
        job = Job.objects.get(pk=response.json()["job_id"])
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertNotIn("PRIVATE", response.json()["error"])


class VariantMigrationTests(TransactionTestCase):
    def test_existing_duplicate_results_are_archived_before_unique_constraint(self):
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        old_target = [("router", "0013_alter_document_source_type")]
        executor.migrate(old_target)
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(targets))
        apps = executor.loader.project_state(old_target).apps
        User, Batch, Result = [apps.get_model("router", name) for name in ("GuestUser", "AnalysisBatch", "AnalysisResult")]
        user = User.objects.create(username="migration", email="migration@example.com")
        batch = Batch.objects.create(user=user, query="q")
        first = Result.objects.create(batch=batch, method="Dense Retrieval", ai_model="model", answer="first", evaluation_metrics=[])
        Result.objects.create(batch=batch, method="Dense Retrieval", ai_model="model", answer="second", evaluation_metrics=[])
        MigrationExecutor(connection).migrate(targets)
        kept = AnalysisResult.objects.get(batch_id=batch.pk)
        self.assertEqual(kept.answer, "second")
        archive = next(metric["value"] for metric in kept.evaluation_metrics if metric["name"] == "superseded_results")
        self.assertEqual(archive[0]["answer"], "first")
        self.assertEqual(archive[0]["id"], first.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AnalysisResult.objects.create(batch_id=batch.pk, method="Dense Retrieval", ai_model="model", answer="duplicate")
