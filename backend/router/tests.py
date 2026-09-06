"""
Tests for the router app: API endpoints, celery tasks, and the retrieval
engine contracts they depend on.

These tests are hermetic: no Redis, no network, no LLM keys.
RAG_DISABLE_ENGINE_INIT must be set before the URLconf (and therefore
rag.rag_service) is imported, which is why it is set at module import time.
"""
import os
import tempfile
from unittest import mock

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

import numpy as np
from django.test import TestCase, override_settings

from router.models import (
    GuestUser,
    Document,
    Job,
    Conversation,
    ConversationHistory,
    AnalysisBatch,
    AnalysisResult,
)
import router.tasks as tasks
from common.schema import get_responses
from common.chunker import DocumentChunker
from common.constant import (
    CONFIG_VARIANTS,
    DEFAULT_CHAT_VARIANT,
    DEFAULT_CHILD_TOP_K,
    DEFAULT_JUDGE_MODEL,
    DEFAULT_POOL_TOP_N,
    DEFAULT_RERANKER_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_K,
    MAX_VARIANTS,
    METHOD_IDS,
    MODEL_IDS,
    POOL_TOP_N_MAX,
    POOL_TOP_N_MIN,
    TEMPERATURE_MAX,
    TOP_K_MAX,
    TOP_K_MIN,
    build_pipeline_config,
    build_variants,
    is_valid_model_id,
    normalize_analysis_config,
)
from rag.rag_service import apply_retrieval_depth
from pipeline.base_pipeline import BasePipeline
from dense_rag.dense_rag import DenseRAG
from ai_handler.llm import OpenRouterLLM
from ai_handler.model_catalog import default_catalog, fetch_catalog

TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="ragreader-test-media-")
LOCMEM_CACHE = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}


def make_user(username="alice", email=None):
    return GuestUser.objects.create(
        username=username, email=email or f"{username}@example.com"
    )


# ── Response helpers ─────────────────────────────────────────────────────────

class ResponseSchemaTests(TestCase):
    def test_response_404_is_a_static_method_returning_404(self):
        # Regression: response_404 was missing @staticmethod, so calling it on
        # the singleton raised TypeError and every 404 surfaced as a 500.
        resp = get_responses().response_404(error="not found")
        self.assertEqual(resp.status_code, 404)

    def test_other_response_helpers(self):
        self.assertEqual(get_responses().response_200("ok").status_code, 200)
        self.assertEqual(get_responses().response_400("bad").status_code, 400)
        self.assertEqual(get_responses().response_500("err").status_code, 500)


# ── API endpoints ────────────────────────────────────────────────────────────

@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class AuthEndpointTests(TestCase):
    def test_sign_up_creates_user(self):
        resp = self.client.post(
            "/api/v1/sign-up/",
            {"EMAIL": "new@example.com", "USERNAME": "newuser"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(GuestUser.objects.filter(username="newuser").exists())

    def test_sign_up_existing_user_returns_200(self):
        make_user("bob")
        resp = self.client.post(
            "/api/v1/sign-up/",
            {"EMAIL": "bob@example.com", "USERNAME": "bob"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class InsertTextEndpointTests(TestCase):
    def test_insert_text_creates_document(self):
        make_user("alice")
        resp = self.client.post(
            "/api/v1/insert-text/",
            {"USER": "alice", "TEXT": "Some document text about testing."},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        doc = Document.objects.get(user__username="alice")
        self.assertTrue(doc.extracted_text_path)

    def test_save_text_returns_actual_stored_path_on_collision(self):
        # Regression: _save_text ignored the deduplicated name returned by
        # default_storage.save, so on a name collision the Document record
        # pointed at the previously stored file.
        from django.core.files.storage import default_storage
        from utils.insert_file import DataLoader

        first = DataLoader._save_text("documents/user_alice/samedir", "first")
        second = DataLoader._save_text("documents/user_alice/samedir", "second")
        self.assertNotEqual(first, second)
        with default_storage.open(second) as f:
            self.assertEqual(f.read().decode(), "second")

    def test_insert_text_unknown_user_errors(self):
        resp = self.client.post(
            "/api/v1/insert-text/",
            {"USER": "ghost", "TEXT": "text"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 500)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class InsertDataEndpointTests(TestCase):
    def test_insert_data_txt_file(self):
        user = make_user("alice")
        from django.core.files.uploadedfile import SimpleUploadedFile
        txt_content = b"This is a plain text document.\nIt contains multiple lines of information."
        uploaded_file = SimpleUploadedFile("sample.txt", txt_content, content_type="text/plain")

        resp = self.client.post(
            "/api/v1/insert-data/",
            {"USER": "alice", "FILE": uploaded_file},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200)
        doc = Document.objects.filter(user=user).latest("created_at")
        self.assertEqual(doc.source_type, "txt")
        self.assertEqual(doc.name, "sample.txt")
        self.assertTrue(doc.extracted_text_path)
        from django.core.files.storage import default_storage
        with default_storage.open(doc.extracted_text_path, "r") as f:
            extracted = f.read()
        self.assertIn("This is a plain text document.", extracted)

    def test_insert_data_markdown_file(self):
        user = make_user("alice")
        from django.core.files.uploadedfile import SimpleUploadedFile
        md_content = b"# Header\n\nThis is a **markdown** document with lists:\n- item 1\n- item 2"
        uploaded_file = SimpleUploadedFile("notes.md", md_content, content_type="text/markdown")

        resp = self.client.post(
            "/api/v1/insert-data/",
            {"USER": "alice", "FILE": uploaded_file},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200)
        doc = Document.objects.filter(user=user).latest("created_at")
        self.assertEqual(doc.source_type, "md")
        self.assertEqual(doc.name, "notes.md")
        self.assertTrue(doc.extracted_text_path)
        from django.core.files.storage import default_storage
        with default_storage.open(doc.extracted_text_path, "r") as f:
            extracted = f.read()
        self.assertIn("**markdown** document", extracted)

    def test_insert_data_pdf_file(self):
        user = make_user("alice")
        from django.core.files.uploadedfile import SimpleUploadedFile
        with mock.patch("utils.insert_file.DataLoader._parse_pdf", return_value="Extracted PDF text content"):
            uploaded_file = SimpleUploadedFile("document.pdf", b"%PDF-1.4 dummy content", content_type="application/pdf")
            resp = self.client.post(
                "/api/v1/insert-data/",
                {"USER": "alice", "FILE": uploaded_file},
                format="multipart",
            )
            self.assertEqual(resp.status_code, 200)
            doc = Document.objects.filter(user=user).latest("created_at")
            self.assertEqual(doc.source_type, "pdf")
            self.assertEqual(doc.name, "document.pdf")
            self.assertTrue(doc.extracted_text_path)

    def test_insert_data_unsupported_file_extension(self):
        make_user("alice")
        from django.core.files.uploadedfile import SimpleUploadedFile
        uploaded_file = SimpleUploadedFile("archive.zip", b"fake zip content", content_type="application/zip")
        resp = self.client.post(
            "/api/v1/insert-data/",
            {"USER": "alice", "FILE": uploaded_file},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)

    def test_insert_data_unknown_user(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        uploaded_file = SimpleUploadedFile("sample.txt", b"hello", content_type="text/plain")
        resp = self.client.post(
            "/api/v1/insert-data/",
            {"USER": "ghost", "FILE": uploaded_file},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 404)

    def test_data_loader_load_supports_all_types(self):
        from utils.insert_file import get_loader
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage
        loader = get_loader()

        # Test txt loading
        txt_path = default_storage.save("test_dir/test.txt", ContentFile("Hello from txt file"))
        loaded_txt = loader.load(txt_path)
        self.assertEqual(loaded_txt, "Hello from txt file")

        # Test md loading
        md_path = default_storage.save("test_dir/test.md", ContentFile("# Markdown text"))
        loaded_md = loader.load(md_path)
        self.assertEqual(loaded_md, "# Markdown text")

        # Test unsupported loading raises
        unsupported_path = default_storage.save("test_dir/test.bin", ContentFile(b"\x00\x01"))
        with self.assertRaises(ValueError):
            loader.load(unsupported_path)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class QueryEndpointTests(TestCase):
    def test_query_without_job_returns_404(self):
        make_user("alice")
        resp = self.client.post(
            "/api/v1/query/",
            {"USER": "alice", "QUERY": "what is this?"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_query_while_initializing_returns_400(self):
        user = make_user("alice")
        Job.objects.create(user=user, status=Job.Status.PROCESSING)
        resp = self.client.post(
            "/api/v1/query/",
            {"USER": "alice", "QUERY": "what is this?"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_query_happy_path_saves_conversation(self):
        user = make_user("alice")
        doc = Document.objects.create(user=user, name="d", source_type="text")
        Job.objects.create(user=user, status=Job.Status.READY, document=doc)

        engine = mock.Mock()
        engine.run.return_value = {
            "answer": "42",
            "context": [{"text": "chunk text", "chunk_id": 1, "score": 0.9}],
            "chunk_ids": [1],
        }
        import router.views as views
        with mock.patch.object(views.rag_registry, "get_engine", return_value=engine):
            resp = self.client.post(
                "/api/v1/query/",
                {"USER": "alice", "QUERY": "meaning of life?"},
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        conversation = Conversation.objects.get(user=user)
        self.assertEqual(conversation.response, "42")
        self.assertTrue(ConversationHistory.objects.filter(user=user).exists())


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class JobAndConversationEndpointTests(TestCase):
    def test_job_status_not_found(self):
        resp = self.client.get(
            "/api/v1/job-status/00000000-0000-0000-0000-000000000000/"
        )
        self.assertEqual(resp.status_code, 404)

    def test_job_status_found(self):
        user = make_user("alice")
        job = Job.objects.create(user=user)
        resp = self.client.get(f"/api/v1/job-status/{job.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_conversation_not_found(self):
        resp = self.client.get("/api/v1/conversation/99999/")
        self.assertEqual(resp.status_code, 404)

    def test_conversation_history_unknown_user_404(self):
        resp = self.client.get("/api/v1/conversation-history/ghost/")
        self.assertEqual(resp.status_code, 404)

    def test_document_unknown_user_404(self):
        # Regression: this endpoint previously 500'd because response_404 was
        # not a staticmethod.
        resp = self.client.get("/api/v1/document/ghost/")
        self.assertEqual(resp.status_code, 404)

    def test_conversation_found(self):
        user = make_user("alice")
        conversation = Conversation.objects.create(
            user=user, query="q", response="r", context="c"
        )
        resp = self.client.get(f"/api/v1/conversation/{conversation.id}/")
        self.assertEqual(resp.status_code, 200)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class OpenChatAndAnalysisEndpointTests(TestCase):
    def test_open_chat_creates_job_and_schedules_task(self):
        make_user("alice")
        import router.views as views
        with mock.patch.object(views, "initialize_rag_task") as task:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(
                    "/api/v1/open-chat/",
                    {"USER": "alice"},
                    content_type="application/json",
                )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(Job.objects.count(), 1)
        task.delay.assert_called_once()

    def test_start_analysis_creates_batch(self):
        user = make_user("alice")
        conversation = Conversation.objects.create(
            user=user, query="q", response="r", context="c"
        )
        resp = self.client.post(
            "/api/v1/start-analysis/",
            {"conversation_id": conversation.id},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(AnalysisBatch.objects.filter(user=user).count(), 1)

    def test_start_analysis_unknown_conversation_404(self):
        resp = self.client.post(
            "/api/v1/start-analysis/",
            {"conversation_id": 424242},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_analysis_status_not_found(self):
        resp = self.client.get(
            "/api/v1/analysis-status/00000000-0000-0000-0000-000000000000/"
        )
        self.assertEqual(resp.status_code, 404)


# ── Celery tasks ─────────────────────────────────────────────────────────────

@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class InitializeRagTaskTests(TestCase):
    def test_success_marks_job_ready(self):
        user = make_user("alice")
        job = Job.objects.create(user=user)
        engine = mock.Mock()
        with mock.patch.object(tasks.rag_registry, "get_engine", return_value=engine):
            result = tasks.initialize_rag_task(
                job_id=str(job.id),
                username="alice",
                method="Dense Retrieval",
                model_config="openai/gpt-4o-mini",
            )
        self.assertTrue(result)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.READY)
        self.assertEqual(job.progress, 100)

    def test_failure_marks_job_failed(self):
        user = make_user("alice")
        job = Job.objects.create(user=user)
        with mock.patch.object(
            tasks.rag_registry, "get_engine", side_effect=Exception("boom")
        ):
            result = tasks.initialize_rag_task(
                job_id=str(job.id),
                username="alice",
                method="Dense Retrieval",
                model_config="openai/gpt-4o-mini",
            )
        self.assertFalse(result)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertIn("boom", job.error_message)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class RunSingleAnalysisTaskTests(TestCase):
    def test_result_is_linked_to_batch_by_job_id(self):
        # Regression: the task passed the batch UUID into the integer FK
        # column, so it could never create a result.
        user = make_user("alice")
        batch = AnalysisBatch.objects.create(user=user, query="q")
        engine = mock.Mock()
        engine.run.return_value = {
            "answer": "hello",
            "context": [{"text": "t", "chunk_id": 1, "score": 0.5}],
        }
        with mock.patch.object(tasks.rag_registry, "get_engine", return_value=engine):
            ok = tasks.run_single_analysis(
                batch_id=str(batch.job_id),
                username="alice",
                query="q",
                variant_config={"method": "Dense Retrieval", "model": "openai/gpt-4o-mini"},
            )
        self.assertTrue(ok)
        result = AnalysisResult.objects.get(batch=batch)
        self.assertEqual(result.answer, "hello")
        self.assertEqual(result.retrieved_chunks[0]["id"], 1)


# ── Engine contracts ─────────────────────────────────────────────────────────

class HybridRetrieveContractTests(TestCase):
    def _make_engine(self):
        from hybrid_rag.hybrid_rag import HybridRAG

        engine = HybridRAG.__new__(HybridRAG)
        engine.final_top_k = 2
        engine.child_top_k = 10
        engine.rrf_k = 60
        engine.sparse_engine = mock.Mock()
        engine.dense_engine = mock.Mock()
        engine._cross_encoder = mock.Mock()
        engine.document_metadata = []
        return engine

    def test_retrieve_returns_chunk_dicts(self):
        # Regression: retrieve() used to return bare strings, crashing every
        # hybrid pipeline at doc["text"].
        engine = self._make_engine()
        engine.sparse_engine.retrieve.return_value = [
            {"text": "alpha", "chunk_id": 1, "score": 1.2}
        ]
        engine.dense_engine.retrieve.return_value = [
            {"text": "beta", "chunk_id": 2, "score": 0.9},
            {"text": "alpha", "chunk_id": 1, "score": 0.8},  # duplicate
        ]
        engine._cross_encoder.predict.return_value = [0.1, 0.9]

        results = engine.retrieve("query")

        self.assertEqual(len(results), 2)
        for doc in results:
            self.assertIn("text", doc)
            self.assertIn("chunk_id", doc)
            self.assertIn("score", doc)
        # Cross-encoder ranked "beta" (0.9) above "alpha" (0.1)
        self.assertEqual(results[0]["text"], "beta")
        self.assertIsInstance(results[0]["score"], float)

    def test_rerank_failure_falls_back_to_candidates(self):
        engine = self._make_engine()
        engine._cross_encoder.predict.side_effect = Exception("model died")
        candidates = [{"text": "a", "chunk_id": 1, "score": 0.5}]
        self.assertEqual(engine._rerank("q", candidates), candidates)

    def test_get_retrieved_scores_uses_rrf_k(self):
        # Regression: rrf_k was documented but never assigned.
        engine = self._make_engine()
        engine.sparse_engine.retrieve.return_value = [
            {"text": "a", "chunk_id": 1, "score": 1.0}
        ]
        engine.dense_engine.retrieve.return_value = [
            {"text": "a", "chunk_id": 1, "score": 0.9}
        ]
        scores = engine.get_retrieved_scores("q")
        self.assertAlmostEqual(scores["scores"]["a"], 2 / 61)


class DenseRetrieveContractTests(TestCase):
    def _make_engine(self):
        engine = DenseRAG.__new__(DenseRAG)
        engine.documents = []
        engine.document_vectors = None
        engine.document_metadata = []
        engine.top_k = 2
        engine.model = "openai/text-embedding-3-small"
        engine.client = mock.Mock()
        return engine

    def test_retrieve_empty_index_returns_empty(self):
        engine = self._make_engine()
        self.assertEqual(engine.retrieve("q"), [])

    def test_embedding_failure_raises_runtime_error(self):
        # Regression: an embeddings API failure used to return [] and then
        # crash with IndexError at [0]; now it raises a clear RuntimeError.
        engine = self._make_engine()
        engine.documents = ["doc"]
        engine.document_vectors = np.array([[1.0, 0.0]])
        engine.document_metadata = [{"chunk_id": 1}]
        engine.client.embeddings.create.side_effect = Exception("api down")
        with self.assertRaises(RuntimeError):
            engine.retrieve("q")

    def test_retrieve_happy_path(self):
        engine = self._make_engine()
        engine.documents = ["hello", "world"]
        engine.document_vectors = np.array([[1.0, 0.0], [0.0, 1.0]])
        engine.document_metadata = [{"chunk_id": 1}, {"chunk_id": 2}]
        engine.client.embeddings.create.return_value = mock.Mock(
            data=[mock.Mock(embedding=[1.0, 0.0])]
        )
        results = engine.retrieve("q")
        self.assertEqual(results[0]["chunk_id"], 1)
        self.assertAlmostEqual(results[0]["score"], 1.0, places=5)

    def test_index_documents_raises_on_no_embeddings(self):
        engine = self._make_engine()
        engine.client.embeddings.create.return_value = mock.Mock(data=[])
        with self.assertRaises(RuntimeError):
            engine.index_documents([{"text": "a", "chunk_id": 1}])


# ── Pipeline helpers ─────────────────────────────────────────────────────────

class BasePipelineHelperTests(TestCase):
    def test_validate_and_clean_query_fallbacks(self):
        clean = BasePipeline._validate_and_clean_query
        self.assertEqual(clean(None, "", "original"), "original")
        self.assertEqual(clean(None, "x" * 300, "original"), "original")
        self.assertEqual(clean(None, "line one\nline two", "original"), "line one")
        self.assertEqual(
            clean(None, 'Optimized query: "better query"', "original"),
            "better query",
        )

    def test_initialize_llm_accepts_openrouter_prefixed_ids(self):
        # Regression: "openai/gpt-4o-mini" (the OpenRouter model ID format)
        # was not recognized and raised ValueError.
        # The OpenAI client refuses to construct without a key, so supply a
        # dummy one — the suite must not depend on a real credential.
        stub = mock.Mock(config={})
        with override_settings(OPENROUTER_API_KEY="test-key"):
            llm = BasePipeline._initialize_llm(stub, "openai/gpt-4o-mini")
        self.assertIsInstance(llm, OpenRouterLLM)
        self.assertEqual(llm.model, "openai/gpt-4o-mini")

    def test_initialize_llm_rejects_unknown_models(self):
        stub = mock.Mock(config={})
        with self.assertRaises(ValueError):
            BasePipeline._initialize_llm(stub, "mystery-model-9000")

    def test_optimize_query_falls_back_on_llm_failure(self):
        stub = mock.Mock()
        stub.llm.prompt_generate.side_effect = RuntimeError("OpenRouter down")
        result = BasePipeline.optimize_query(stub, "my original query")
        self.assertEqual(result, "my original query")


class ChunkerTests(TestCase):
    def test_fixed_chunking_respects_size(self):
        chunker = DocumentChunker(strategy="fixed", chunk_size=10, overlap=2)
        chunks = chunker.chunk("abcdefghijklmnopqrstuvwxyz")
        self.assertTrue(all(len(c) <= 10 for c in chunks))
        self.assertEqual(chunks[0], "abcdefghij")
        self.assertTrue(chunks[1].startswith("ij"))  # overlap preserved

    def test_paragraph_chunking_falls_back_to_single_newlines(self):
        chunker = DocumentChunker(strategy="paragraph", chunk_size=500, overlap=50)
        chunks = chunker.chunk("para one\npara two")
        self.assertEqual(len(chunks), 1)
        self.assertIn("para one", chunks[0])
        self.assertIn("para two", chunks[0])

    def test_unknown_strategy_raises(self):
        chunker = DocumentChunker(strategy="bogus")
        with self.assertRaises(ValueError):
            chunker.chunk("text")


# ── Deep-analysis configuration ──────────────────────────────────────────────

class AnalysisConfigTests(TestCase):
    def test_defaults_run_the_full_matrix(self):
        config = normalize_analysis_config(None)
        self.assertEqual(config["methods"], METHOD_IDS)
        self.assertEqual(config["models"], MODEL_IDS)
        self.assertEqual(config["top_k"], DEFAULT_TOP_K)
        self.assertEqual(config["ground_truth_mode"], "manual")
        self.assertEqual(len(build_variants(config)), len(CONFIG_VARIANTS))

    def test_narrowing_the_selection(self):
        config = normalize_analysis_config({
            "methods": ["Dense Retrieval", "Hybrid Retrieval"],
            "models": ["openai/gpt-4o-mini"],
            "top_k": 3,
            "ground_truth_mode": "pooled",
        })
        self.assertEqual(len(build_variants(config)), 2)
        self.assertEqual(config["top_k"], 3)
        self.assertEqual(config["ground_truth_mode"], "pooled")

    def test_unknown_options_are_dropped_not_fatal(self):
        config = normalize_analysis_config({
            "methods": ["Dense Retrieval", "Telepathic Retrieval"],
            "models": ["openai/gpt-4o-mini", "gpt-5-imaginary"],
        })
        self.assertEqual(config["methods"], ["Dense Retrieval"])
        self.assertEqual(config["models"], ["openai/gpt-4o-mini"])

    def test_empty_selection_falls_back_to_everything(self):
        config = normalize_analysis_config({"methods": [], "models": []})
        self.assertEqual(config["methods"], METHOD_IDS)
        self.assertEqual(config["models"], MODEL_IDS)

    def test_top_k_is_clamped_and_junk_tolerated(self):
        self.assertEqual(normalize_analysis_config({"top_k": 999})["top_k"], TOP_K_MAX)
        self.assertEqual(normalize_analysis_config({"top_k": 0})["top_k"], TOP_K_MIN)
        self.assertEqual(normalize_analysis_config({"top_k": "abc"})["top_k"], DEFAULT_TOP_K)

    def test_unknown_ground_truth_mode_falls_back(self):
        config = normalize_analysis_config({"ground_truth_mode": "vibes"})
        self.assertEqual(config["ground_truth_mode"], "manual")

    def test_the_chat_variant_is_still_dense_gpt4o_mini(self):
        # OpenChatView and QueryView both use DEFAULT_CHAT_VARIANT for the
        # standard (non-deep) chat path. It used to be CONFIG_VARIANTS[0]; the
        # pair is named now precisely so it can't drift when the matrix does.
        self.assertEqual(
            DEFAULT_CHAT_VARIANT,
            {"method": "Dense Retrieval", "model": "openai/gpt-4o-mini"},
        )
        self.assertEqual(DEFAULT_CHAT_VARIANT, CONFIG_VARIANTS[0])


class RetrievalDepthTests(TestCase):
    def test_dense_and_sparse_engines_take_top_k_directly(self):
        engine = mock.Mock()
        engine.rag = mock.Mock(spec=["top_k"])
        engine.rag.top_k = 5
        apply_retrieval_depth(engine, 12)
        self.assertEqual(engine.rag.top_k, 12)

    def test_hybrid_children_fetch_deeper_than_the_final_cut(self):
        # A reranker with only top_k candidates has nothing to rerank, and a
        # final_top_k above child_top_k would silently truncate.
        engine = mock.Mock()
        engine.rag = mock.Mock(spec=["final_top_k", "child_top_k", "dense_engine", "sparse_engine"])
        engine.rag.dense_engine = mock.Mock(spec=["top_k"])
        engine.rag.sparse_engine = mock.Mock(spec=["top_k"])

        apply_retrieval_depth(engine, 15)

        self.assertEqual(engine.rag.final_top_k, 15)
        self.assertEqual(engine.rag.child_top_k, 30)
        self.assertEqual(engine.rag.dense_engine.top_k, 30)
        self.assertEqual(engine.rag.sparse_engine.top_k, 30)

    def test_depth_does_not_drift_across_runs(self):
        # Engines are shared singletons; a deep run followed by a shallow one
        # must land on the shallow config exactly.
        engine = mock.Mock()
        engine.rag = mock.Mock(spec=["final_top_k", "child_top_k", "dense_engine", "sparse_engine"])
        engine.rag.dense_engine = mock.Mock(spec=["top_k"])
        engine.rag.sparse_engine = mock.Mock(spec=["top_k"])

        apply_retrieval_depth(engine, 20)
        apply_retrieval_depth(engine, 3)

        self.assertEqual(engine.rag.final_top_k, 3)
        self.assertEqual(engine.rag.child_top_k, 10)
        self.assertEqual(engine.rag.dense_engine.top_k, 10)

    def test_engine_without_a_rag_attribute_is_ignored(self):
        apply_retrieval_depth(mock.Mock(rag=None), 5)  # must not raise


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class ChatRetrievalDepthTests(TestCase):
    """Chat shares its engine with deep analysis and candidate pooling."""

    def test_query_resets_depth_left_behind_by_pooling(self):
        # Regression: QueryView called .run() straight off the registry. The
        # engine is a process-wide singleton that candidate pooling re-depths
        # to as much as POOL_TOP_N_MAX, so the next chat message silently
        # retrieved that many chunks instead of DEFAULT_TOP_K.
        user = make_user("alice")
        doc = Document.objects.create(user=user, name="d", source_type="text")
        Job.objects.create(user=user, status=Job.Status.READY, document=doc)

        engine = mock.Mock()
        engine.rag = mock.Mock(spec=["top_k"])
        engine.rag.top_k = POOL_TOP_N_MAX  # what pooling left behind
        engine.run.return_value = {
            "answer": "42",
            "context": [{"text": "chunk text", "chunk_id": 1, "score": 0.9}],
            "chunk_ids": [1],
        }

        import router.views as views
        with mock.patch.object(views.rag_registry, "get_engine", return_value=engine):
            resp = self.client.post(
                "/api/v1/query/",
                {"USER": "alice", "QUERY": "meaning of life?"},
                content_type="application/json",
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(engine.rag.top_k, DEFAULT_TOP_K)

    def test_query_pins_depth_before_running_not_after(self):
        # Pinning after .run() would be a no-op for the request that needs it.
        user = make_user("alice")
        doc = Document.objects.create(user=user, name="d", source_type="text")
        Job.objects.create(user=user, status=Job.Status.READY, document=doc)

        engine = mock.Mock()
        engine.rag = mock.Mock(spec=["top_k"])
        engine.rag.top_k = TOP_K_MAX

        depth_at_run_time = {}

        def record_depth(username, query):
            depth_at_run_time["top_k"] = engine.rag.top_k
            return {"answer": "a", "context": [], "chunk_ids": []}

        engine.run.side_effect = record_depth

        import router.views as views
        with mock.patch.object(views.rag_registry, "get_engine", return_value=engine):
            self.client.post(
                "/api/v1/query/",
                {"USER": "alice", "QUERY": "q"},
                content_type="application/json",
            )

        self.assertEqual(depth_at_run_time["top_k"], DEFAULT_TOP_K)


class HybridChildDepthTests(TestCase):
    def test_children_are_built_at_child_top_k_not_final_top_k(self):
        # Regression: HybridRAG passed `config` straight to its sub-engines, so
        # they fetched `top_k` candidates — leaving the cross-encoder with
        # exactly as many candidates as it was asked to return, i.e. nothing to
        # rerank until apply_retrieval_depth happened to be called.
        import hybrid_rag.hybrid_rag as hybrid_module

        hybrid_module.clear_cross_encoder_cache()
        self.addCleanup(hybrid_module.clear_cross_encoder_cache)

        with mock.patch.object(hybrid_module, "SparseRAG") as sparse_cls, \
             mock.patch.object(hybrid_module, "DenseRAG") as dense_cls, \
             mock.patch.object(hybrid_module, "OllamaCrossEncoder"):
            engine = hybrid_module.HybridRAG({"top_k": 5, "child_top_k": 10})

        self.assertEqual(engine.final_top_k, 5)
        for cls in (sparse_cls, dense_cls):
            child_config = cls.call_args.args[0]
            self.assertEqual(child_config["top_k"], 10)
            self.assertEqual(child_config["child_top_k"], 10)

    def test_caller_config_is_not_mutated(self):
        import hybrid_rag.hybrid_rag as hybrid_module

        hybrid_module.clear_cross_encoder_cache()
        self.addCleanup(hybrid_module.clear_cross_encoder_cache)

        config = {"top_k": 5, "child_top_k": 10}
        with mock.patch.object(hybrid_module, "SparseRAG"), \
             mock.patch.object(hybrid_module, "DenseRAG"), \
             mock.patch.object(hybrid_module, "OllamaCrossEncoder"):
            hybrid_module.HybridRAG(config)

        # RAGRegistry hands the same dict shape to every variant.
        self.assertEqual(config["top_k"], 5)


class PoolTopNConfigTests(TestCase):
    def test_pool_top_n_is_clamped_and_junk_tolerated(self):
        self.assertEqual(
            normalize_analysis_config({"pool_top_n": 9999})["pool_top_n"],
            POOL_TOP_N_MAX,
        )
        self.assertEqual(
            normalize_analysis_config({"pool_top_n": 0})["pool_top_n"],
            POOL_TOP_N_MIN,
        )
        self.assertEqual(
            normalize_analysis_config({"pool_top_n": "abc"})["pool_top_n"],
            DEFAULT_POOL_TOP_N,
        )

    def test_pool_is_deeper_than_a_single_run(self):
        # If the pool were as shallow as one run's output, the pooled ground
        # truth would be close to a copy of that run and the retrieval metrics
        # would flatter it.
        self.assertGreater(DEFAULT_POOL_TOP_N, DEFAULT_TOP_K)


class OpenModelSelectionTests(TestCase):
    """Any OpenRouter model is runnable; the shipped three are just defaults."""

    def test_a_model_outside_the_defaults_survives_normalization(self):
        # The old contract dropped unrecognised ids, which is exactly what made
        # the selector a fixed list of three.
        config = normalize_analysis_config({"models": ["deepseek/deepseek-chat"]})
        self.assertEqual(config["models"], ["deepseek/deepseek-chat"])

    def test_the_order_the_client_sent_is_kept(self):
        # MAX_VARIANTS trims from the end, so order is not cosmetic.
        chosen = ["z/last", "a/first"]
        self.assertEqual(normalize_analysis_config({"models": chosen})["models"], chosen)

    def test_malformed_ids_are_dropped_not_run(self):
        config = normalize_analysis_config(
            {"models": ["openai/gpt-4o-mini", "no-slash", "", None, 42]}
        )
        self.assertEqual(config["models"], ["openai/gpt-4o-mini"])

    def test_a_selection_of_only_junk_falls_back_to_the_defaults(self):
        self.assertEqual(normalize_analysis_config({"models": ["???"]})["models"], MODEL_IDS)

    def test_duplicates_are_collapsed(self):
        config = normalize_analysis_config(
            {"models": ["openai/gpt-4o-mini", "openai/gpt-4o-mini"]}
        )
        self.assertEqual(config["models"], ["openai/gpt-4o-mini"])

    def test_model_id_shape(self):
        for good in (
            "openai/gpt-4o-mini",
            "openai/gpt-4o-mini-2024-07-18",
            "meta-llama/llama-3.3-70b-instruct:free",
            "x-ai/grok-2",
        ):
            self.assertTrue(is_valid_model_id(good), good)

        for bad in ("", "gpt-4o", "openai/", "/gpt-4o", "open ai/gpt", None, 7, "a/" + "x" * 200):
            self.assertFalse(is_valid_model_id(bad), repr(bad))


class VariantCapTests(TestCase):
    """One variant is a full retrieve-generate-judge cycle, so the matrix is capped."""

    def test_the_default_matrix_still_fits(self):
        # Nine (3 methods x 3 models) must stay reachable or the shipped
        # defaults would be silently trimmed on every run.
        self.assertEqual(len(build_variants(None)), len(CONFIG_VARIANTS))

    def test_too_many_models_are_trimmed_rather_than_run(self):
        many = [f"vendor/model-{n}" for n in range(40)]
        config = normalize_analysis_config({"methods": METHOD_IDS, "models": many})
        self.assertLessEqual(len(config["methods"]) * len(config["models"]), MAX_VARIANTS)
        self.assertEqual(config["models"], many[: len(config["models"])])

    def test_narrowing_the_methods_buys_more_models(self):
        many = [f"vendor/model-{n}" for n in range(40)]
        one_method = normalize_analysis_config(
            {"methods": ["Hybrid Retrieval"], "models": many}
        )
        all_methods = normalize_analysis_config({"methods": METHOD_IDS, "models": many})
        self.assertGreater(len(one_method["models"]), len(all_methods["models"]))

    def test_the_variant_list_never_exceeds_the_cap(self):
        many = [f"vendor/model-{n}" for n in range(40)]
        variants = build_variants({"methods": METHOD_IDS, "models": many})
        self.assertLessEqual(len(variants), MAX_VARIANTS)


class PerRunKnobTests(TestCase):
    """The Tier-A settings the sidebar can change, and their clamps."""

    def test_defaults_are_filled_in_for_a_config_that_predates_them(self):
        # AnalysisBatch.config rows written before these keys existed must
        # still replay rather than KeyError.
        config = normalize_analysis_config({"methods": METHOD_IDS, "top_k": 5})
        self.assertEqual(config["temperature"], DEFAULT_TEMPERATURE)
        self.assertEqual(config["child_top_k"], DEFAULT_CHILD_TOP_K)
        self.assertEqual(config["reranker_model"], DEFAULT_RERANKER_MODEL)
        self.assertEqual(config["judge_model"], DEFAULT_JUDGE_MODEL)

    def test_temperature_is_clamped_and_junk_tolerated(self):
        self.assertEqual(normalize_analysis_config({"temperature": 99})["temperature"], TEMPERATURE_MAX)
        self.assertEqual(normalize_analysis_config({"temperature": -1})["temperature"], 0.0)
        self.assertEqual(
            normalize_analysis_config({"temperature": "hot"})["temperature"],
            DEFAULT_TEMPERATURE,
        )
        self.assertEqual(normalize_analysis_config({"temperature": 0.7})["temperature"], 0.7)

    def test_an_unknown_reranker_falls_back_to_the_default(self):
        # Rerankers run on this server rather than through OpenRouter, so the
        # set is closed: an arbitrary string would be an arbitrary download.
        config = normalize_analysis_config({"reranker_model": "evil/backdoor"})
        self.assertEqual(config["reranker_model"], DEFAULT_RERANKER_MODEL)

    def test_the_judge_model_is_open_like_any_other_model(self):
        config = normalize_analysis_config({"judge_model": "qwen/qwen-2.5-72b-instruct"})
        self.assertEqual(config["judge_model"], "qwen/qwen-2.5-72b-instruct")
        self.assertEqual(
            normalize_analysis_config({"judge_model": "nonsense"})["judge_model"],
            DEFAULT_JUDGE_MODEL,
        )

    def test_pipeline_config_merges_ingest_defaults_with_run_choices(self):
        built = build_pipeline_config({"temperature": 0.4}, "deepseek/deepseek-chat")
        self.assertEqual(built["llm_model"], "deepseek/deepseek-chat")
        self.assertEqual(built["temperature"], 0.4)
        # Both spellings of the embedding model resolve to the same value.
        self.assertEqual(built["embedding_model"], built["model"])
        self.assertIn("chunk_size", built)

    def test_pipeline_config_refuses_to_pass_a_malformed_model_through(self):
        built = build_pipeline_config(None, "not-a-model")
        self.assertTrue(is_valid_model_id(built["llm_model"]))


@override_settings(CACHES=LOCMEM_CACHE)
class ModelCatalogTests(TestCase):
    """The selector's list: live when OpenRouter answers, defaults when not."""

    OPENROUTER_PAYLOAD = {
        "data": [
            {
                "id": "deepseek/deepseek-chat",
                "name": "DeepSeek V3",
                "context_length": 64000,
                "pricing": {"prompt": "0.00000027", "completion": "0.0000011"},
                "architecture": {"output_modalities": ["text"]},
            },
            {
                "id": "openai/text-embedding-3-small",
                "name": "Embedding",
                "architecture": {"output_modalities": ["embedding"]},
            },
            {"id": "not a model id", "name": "Junk"},
        ]
    }

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _fetch(self, **kwargs):
        return fetch_catalog(**kwargs)

    def test_a_live_catalogue_is_normalized(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = self.OPENROUTER_PAYLOAD
        with mock.patch("ai_handler.model_catalog.requests.get", return_value=response):
            result = self._fetch()

        self.assertEqual(result["source"], "openrouter")
        ids = [m["id"] for m in result["models"]]
        self.assertIn("deepseek/deepseek-chat", ids)
        # Embedding-only and malformed entries are not generation models.
        self.assertNotIn("openai/text-embedding-3-small", ids)
        self.assertNotIn("not a model id", ids)

    def test_the_shipped_defaults_are_always_present_and_first(self):
        # Losing one would silently change what the sidebar pre-selects.
        response = mock.Mock(status_code=200)
        response.json.return_value = self.OPENROUTER_PAYLOAD
        with mock.patch("ai_handler.model_catalog.requests.get", return_value=response):
            result = self._fetch()

        ids = [m["id"] for m in result["models"]]
        self.assertEqual(ids[: len(MODEL_IDS)], MODEL_IDS)

    def test_pricing_and_context_are_carried_through(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = self.OPENROUTER_PAYLOAD
        with mock.patch("ai_handler.model_catalog.requests.get", return_value=response):
            result = self._fetch()

        entry = next(m for m in result["models"] if m["id"] == "deepseek/deepseek-chat")
        self.assertEqual(entry["context_length"], 64000)
        self.assertAlmostEqual(entry["prompt_price"], 0.00000027)
        self.assertEqual(entry["provider"], "DeepSeek")
        self.assertFalse(entry["is_default"])

    def test_a_network_failure_falls_back_to_the_defaults(self):
        # The catalogue is a convenience; the selector must stay usable.
        with mock.patch(
            "ai_handler.model_catalog.requests.get", side_effect=OSError("no route")
        ):
            result = self._fetch()

        self.assertEqual(result["source"], "defaults")
        self.assertEqual([m["id"] for m in result["models"]], MODEL_IDS)
        self.assertIn("no route", result["error"])

    def test_an_unexpected_payload_falls_back_to_the_defaults(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"unexpected": True}
        with mock.patch("ai_handler.model_catalog.requests.get", return_value=response):
            result = self._fetch()

        self.assertEqual(result["source"], "defaults")

    def test_a_successful_fetch_is_cached(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = self.OPENROUTER_PAYLOAD
        with mock.patch(
            "ai_handler.model_catalog.requests.get", return_value=response
        ) as get:
            fetch_catalog()
            fetch_catalog()

        self.assertEqual(get.call_count, 1)

    def test_a_fallback_is_not_cached(self):
        # Otherwise one blip would pin the short list for six hours.
        response = mock.Mock(status_code=200)
        response.json.return_value = self.OPENROUTER_PAYLOAD
        with mock.patch(
            "ai_handler.model_catalog.requests.get", side_effect=OSError("blip")
        ):
            self.assertEqual(fetch_catalog()["source"], "defaults")
        with mock.patch(
            "ai_handler.model_catalog.requests.get", return_value=response
        ):
            self.assertEqual(fetch_catalog()["source"], "openrouter")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CACHES=LOCMEM_CACHE)
class AnalysisConfigEndpointTests(TestCase):
    def _get_config(self, catalog=None):
        """Fetch the endpoint with the catalogue stubbed.

        Never let this test reach the network: on a machine with connectivity
        it would assert against whatever OpenRouter happens to serve today.
        """
        catalog = catalog or {
            "models": default_catalog(),
            "source": "defaults",
            "error": None,
        }
        with mock.patch("router.views.fetch_catalog", return_value=catalog):
            resp = self.client.get("/api/v1/analysis-config/")
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_config_endpoint_lists_the_default_models_and_methods(self):
        body = self._get_config()
        self.assertEqual([m["id"] for m in body["models"]], MODEL_IDS)
        self.assertEqual(body["default_models"], MODEL_IDS)
        self.assertEqual([m["id"] for m in body["retrieval_methods"]], METHOD_IDS)
        self.assertEqual(body["top_k"]["default"], DEFAULT_TOP_K)
        self.assertEqual(body["max_variants"], MAX_VARIANTS)
        self.assertGreaterEqual(MAX_VARIANTS, len(CONFIG_VARIANTS))

    def test_config_endpoint_serves_the_whole_per_run_option_set(self):
        # The sidebar renders from this payload; a missing range means a
        # control silently falls back to a hardcoded guess in the browser.
        body = self._get_config()
        self.assertEqual(body["temperature"]["default"], DEFAULT_TEMPERATURE)
        self.assertEqual(body["temperature"]["max"], TEMPERATURE_MAX)
        self.assertEqual(body["child_top_k"]["default"], DEFAULT_CHILD_TOP_K)
        self.assertIn("rrf_k", body)
        self.assertEqual(body["judge_model"]["default"], DEFAULT_JUDGE_MODEL)
        self.assertIn(DEFAULT_RERANKER_MODEL, [r["id"] for r in body["rerankers"]])
        # Ingest settings are reported so the UI can show what they actually
        # are, but they are not part of the per-run config.
        self.assertIn("embedding_model", body["ingest"])
        self.assertNotIn("embedding_model", body["defaults"])

    def test_config_endpoint_says_where_the_model_list_came_from(self):
        body = self._get_config({
            "models": default_catalog(),
            "source": "defaults",
            "error": "connection refused",
        })
        self.assertEqual(body["model_catalog"]["source"], "defaults")
        self.assertEqual(body["model_catalog"]["error"], "connection refused")
        self.assertEqual(body["model_catalog"]["count"], len(MODEL_IDS))

    def test_start_analysis_stores_the_chosen_config(self):
        user = make_user("alice")
        conversation = Conversation.objects.create(
            user=user, query="q", response="r", context="c"
        )
        resp = self.client.post(
            "/api/v1/start-analysis/",
            {
                "conversation_id": conversation.id,
                "config": {
                    "methods": ["Dense Retrieval"],
                    "models": ["openai/gpt-4o-mini", "anthropic/claude-haiku-4.5"],
                    "top_k": 8,
                    "ground_truth_mode": "pooled",
                },
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["expected_count"], 2)

        batch = AnalysisBatch.objects.get(user=user)
        self.assertEqual(batch.total_variants, 2)
        self.assertEqual(batch.config["top_k"], 8)
        self.assertEqual(batch.config["methods"], ["Dense Retrieval"])

    def test_start_analysis_without_config_runs_everything(self):
        user = make_user("alice")
        conversation = Conversation.objects.create(
            user=user, query="q", response="r", context="c"
        )
        resp = self.client.post(
            "/api/v1/start-analysis/",
            {"conversation_id": conversation.id},
            content_type="application/json",
        )
        self.assertEqual(resp.json()["expected_count"], len(CONFIG_VARIANTS))

    def test_start_analysis_reports_the_ground_truth_actually_stored(self):
        from evaluation.models import Chunk, GroundTruthChunk

        user = make_user("alice")
        document = Document.objects.create(user=user, name="d", source_type="text")
        conversation = Conversation.objects.create(
            user=user, document=document, query="q", response="r", context="c"
        )
        chunk = Chunk.objects.create(document=document, text="t")
        GroundTruthChunk.objects.create(
            conversation=conversation,
            chunk=chunk,
            source=GroundTruthChunk.Source.POOLED,
        )
        resp = self.client.post(
            "/api/v1/start-analysis/",
            {"conversation_id": conversation.id},
            content_type="application/json",
        )
        self.assertEqual(resp.json()["ground_truth"], {"count": 1, "source": "pooled"})
