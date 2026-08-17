"""
Tests for the pipeline layer: `pipeline/`, the engines it drives, and the
registry that hands them out.

`router/tests.py` covers the API endpoints, the celery tasks, and the *retrieval
contracts* of the engines. This module covers the layer in between — the part
that turns a Document into an index, a query into an answer, and an answer into
evaluated results:

    BasePipeline        chunk sync, document lookup, init detection
    DenseRAGPipeline    state round-trip, init/reuse/rebuild, run, run_analysis
    SparseRAGPipeline   the same flow over BM25
    HybridRAGPipeline   two-engine state, the reranked run
    RAGRegistry         the method × model matrix and its lookups
    DataLoader.load     the text read every _build_index() starts from

Hermetic, like the rest of the suite: no Redis, no database server, no network,
no API keys. Everything that would reach out is patched at its boundary —
embeddings, LLM calls, the cross-encoder — while the pipeline code under test
runs for real.

Two boundaries are worth naming, because they are the reason for the patches
rather than an arbitrary choice:

* `SparseRAG.__init__` reads NLTK's English stopword list and `_tokenize` calls
  `word_tokenize`, both of which need corpora that are downloaded at import
  time. Tests pass `remove_stop_words: False` and patch `word_tokenize`, so a
  missing corpus can never be the reason a pipeline test fails.
* `HybridRAG.__init__` constructs a `CrossEncoder`, which downloads a model on
  first use. Tests patch the class and score with a stub.
"""
import os
import pickle
import shutil
import tempfile
from unittest import mock

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

import numpy as np
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

import rag.rag_service as rag_service
from evaluation.models import Chunk, GroundTruthChunk, GroundTruthResponse
from pipeline.base_pipeline import BasePipeline
from pipeline.dense_rag_pipeline import DenseRAGPipeline
from pipeline.hybrid_rag_pipeline import HybridRAGPipeline
from pipeline.sparse_rag_pipeline import SparseRAGPipeline
from router.models import (
    Conversation,
    Document,
    DocumentVector,
    GuestUser,
    Job,
    VectorStore,
)
from utils.insert_file import DataLoader

TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="ragreader-test-pipeline-media-")

DOCUMENT_TEXT = (
    "Alpha paragraph about vector embeddings.\n\n"
    "Beta paragraph about keyword search.\n\n"
    "Gamma paragraph about reranking."
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def make_user(username="alice", email=None):
    return GuestUser.objects.create(
        username=username, email=email or f"{username}@example.com"
    )


def make_document(user, text=DOCUMENT_TEXT, name="doc.txt"):
    """A Document whose extracted text really exists in storage.

    `_build_index` starts by reading `extracted_text_path` through
    `DataLoader.load`, so a document with a dangling path exercises the error
    path rather than the pipeline.
    """
    path = default_storage.save(
        f"documents/user_{user.username}/extracted.txt", ContentFile(text)
    )
    return Document.objects.create(
        user=user,
        name=name,
        source_type="text",
        extracted_text_path=path,
        source_path=path,
    )


def _vector_for(text: str):
    """Deterministic stand-in for an embedding.

    One axis per keyword in DOCUMENT_TEXT, so "which chunk is nearest" is a
    fact about the retrieval code rather than about a random vector.
    """
    lowered = text.lower()
    return [
        1.0 if "alpha" in lowered else 0.0,
        1.0 if "beta" in lowered else 0.0,
        1.0 if "gamma" in lowered else 0.0,
    ]


def fake_embeddings_create(input, model=None, **kwargs):  # noqa: A002 - openai kwarg name
    texts = [input] if isinstance(input, str) else list(input)
    return mock.Mock(data=[mock.Mock(embedding=_vector_for(t)) for t in texts])


def simple_tokenize(text):
    """Whitespace tokenizer standing in for NLTK's `word_tokenize`."""
    return text.split()


BASE_CONFIG = {
    "llm_model": "openai/gpt-4o-mini",
    "model": "openai/text-embedding-3-small",
    "top_k": 2,
    "child_top_k": 4,
    "chunk_strategy": "paragraph",
    # Just above the longest paragraph in DOCUMENT_TEXT, so each paragraph
    # becomes exactly one chunk and "which chunk came back" stays meaningful.
    "chunk_size": 45,
    "overlap": 0,
    # Keeps SparseRAG.__init__ away from NLTK's stopword corpus.
    "remove_stop_words": False,
}


class FakeCrossEncoder:
    """Stand-in for sentence-transformers' CrossEncoder.

    Scores by keyword so the reranked order is predictable: alpha > beta >
    everything else.
    """

    def __init__(self, model_name, *args, **kwargs):
        self.model_name = model_name

    def predict(self, pairs):
        scores = []
        for _query, text in pairs:
            lowered = text.lower()
            if "alpha" in lowered:
                scores.append(0.9)
            elif "beta" in lowered:
                scores.append(0.5)
            else:
                scores.append(0.1)
        return np.array(scores)


class PipelineTestCase(TestCase):
    """Shared plumbing: a temp vector-store dir and patched boundaries."""

    def setUp(self):
        self.vector_store_path = tempfile.mkdtemp(prefix="ragreader-test-vs-")
        self.addCleanup(shutil.rmtree, self.vector_store_path, ignore_errors=True)

        tokenize_patch = mock.patch(
            "sparse_rag.sparse_rag.word_tokenize", side_effect=simple_tokenize
        )
        tokenize_patch.start()
        self.addCleanup(tokenize_patch.stop)

        cross_encoder_patch = mock.patch(
            "hybrid_rag.hybrid_rag.CrossEncoder", FakeCrossEncoder
        )
        cross_encoder_patch.start()
        self.addCleanup(cross_encoder_patch.stop)

    def _config(self, **overrides):
        return {
            **BASE_CONFIG,
            "vector_store_path": self.vector_store_path,
            **overrides,
        }

    def make_pipeline(self, cls, **overrides):
        """Build a real pipeline, then replace only what would leave the process."""
        with override_settings(OPENROUTER_API_KEY="test-key"):
            pipeline = cls(self._config(**overrides))

        pipeline.llm = mock.Mock()
        pipeline.llm.rag_generate.return_value = "generated answer"
        pipeline.llm.prompt_generate.return_value = "optimized query"

        for engine in self._embedding_engines(pipeline):
            engine.client = mock.Mock()
            engine.client.embeddings.create.side_effect = fake_embeddings_create

        return pipeline

    @staticmethod
    def _embedding_engines(pipeline):
        rag = pipeline.rag
        dense = getattr(rag, "dense_engine", None)
        if dense is not None:
            return [dense]
        return [rag] if hasattr(rag, "client") else []


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, OPENROUTER_API_KEY="test-key")
class BasePipelineChunkSyncTests(PipelineTestCase):
    """`BasePipeline._sync_chunks` — the DB side of indexing."""

    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.document = make_document(self.user)
        self.pipeline = self.make_pipeline(DenseRAGPipeline)

    def test_new_chunks_are_created_in_document_order(self):
        chunks = ["first", "second", "third"]
        result = self.pipeline._sync_chunks(self.document, chunks)

        self.assertEqual([c["text"] for c in result], chunks)
        self.assertEqual(Chunk.objects.filter(document=self.document).count(), 3)
        for entry in result:
            self.assertIsNotNone(entry["chunk_id"])

    def test_identical_input_reuses_the_same_rows(self):
        first = self.pipeline._sync_chunks(self.document, ["a", "b"])
        second = self.pipeline._sync_chunks(self.document, ["a", "b"])

        self.assertEqual(
            [c["chunk_id"] for c in first], [c["chunk_id"] for c in second]
        )
        self.assertEqual(Chunk.objects.filter(document=self.document).count(), 2)

    def test_changing_the_chunk_config_replaces_every_chunk(self):
        old = self.pipeline._sync_chunks(self.document, ["a", "b"])

        # A different chunk size is a different config_hash, which is what
        # makes the stored chunks (and any ground truth on them) stale.
        self.pipeline.chunker.chunk_size = 999
        new = self.pipeline._sync_chunks(self.document, ["a", "b"])

        self.assertNotEqual(
            {c["chunk_id"] for c in old}, {c["chunk_id"] for c in new}
        )
        self.assertEqual(Chunk.objects.filter(document=self.document).count(), 2)
        self.assertFalse(
            Chunk.objects.filter(id__in=[c["chunk_id"] for c in old]).exists()
        )

    def test_chunks_that_disappear_are_deleted(self):
        self.pipeline._sync_chunks(self.document, ["keep", "drop"])
        result = self.pipeline._sync_chunks(self.document, ["keep"])

        self.assertEqual([c["text"] for c in result], ["keep"])
        self.assertEqual(
            list(
                Chunk.objects.filter(document=self.document).values_list(
                    "text", flat=True
                )
            ),
            ["keep"],
        )

    def test_repeated_text_maps_both_positions_to_one_chunk(self):
        # Regression: a document containing the same text twice (repeated
        # boilerplate, a duplicated heading) used to hit the
        # unique_chunk_per_config constraint and abort indexing entirely.
        result = self.pipeline._sync_chunks(self.document, ["same", "other", "same"])

        self.assertEqual([c["text"] for c in result], ["same", "other", "same"])
        self.assertEqual(result[0]["chunk_id"], result[2]["chunk_id"])
        self.assertEqual(Chunk.objects.filter(document=self.document).count(), 2)

    def test_config_hash_tracks_the_chunker_settings(self):
        before = self.pipeline._get_config_hash()
        self.assertEqual(before, self.pipeline._get_config_hash())

        self.pipeline.chunker.overlap += 10
        self.assertNotEqual(before, self.pipeline._get_config_hash())

    def test_chunk_metadata_records_how_it_was_produced(self):
        self.pipeline._sync_chunks(self.document, ["a"])
        chunk = Chunk.objects.get(document=self.document)

        self.assertEqual(
            chunk.metadata,
            {
                "strategy": self.pipeline.chunker.strategy,
                "chunk_size": self.pipeline.chunker.chunk_size,
                "overlap": self.pipeline.chunker.overlap,
            },
        )


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, OPENROUTER_API_KEY="test-key")
class BasePipelineDocumentTests(PipelineTestCase):
    """Document lookup and "is this variant already indexed?" detection."""

    def setUp(self):
        super().setUp()
        self.pipeline = self.make_pipeline(DenseRAGPipeline)

    def test_get_document_returns_the_users_latest_document(self):
        user = make_user()
        make_document(user, name="old.txt")
        newest = make_document(user, name="new.txt")

        self.assertEqual(self.pipeline.get_document("alice").pk, newest.pk)

    def test_get_document_for_unknown_user_is_none_not_an_error(self):
        self.assertIsNone(self.pipeline.get_document("nobody"))

    def test_is_initialized_false_without_a_document(self):
        self.assertFalse(self.pipeline.is_initialized("nobody"))

    def test_is_initialized_false_without_a_ready_vector_record(self):
        user = make_user()
        make_document(user)
        self.assertFalse(self.pipeline.is_initialized("alice"))

    def test_is_initialized_false_when_the_index_file_is_gone(self):
        # A DocumentVector row is not proof of an index: the .pkl it points at
        # can be removed by a volume reset while the row survives.
        user = make_user()
        document = make_document(user)
        vs = VectorStore.objects.create(base_path=self.vector_store_path)
        DocumentVector.objects.create(
            document=document,
            vectorstore=vs,
            vectorstore_location=os.path.join(self.vector_store_path, "missing.pkl"),
            document_location=document.extracted_text_path,
            status="ready",
            method="dense",
        )
        self.assertFalse(self.pipeline.is_initialized("alice"))

    def test_is_initialized_true_when_record_and_file_both_exist(self):
        user = make_user()
        document = make_document(user)
        path = os.path.join(self.vector_store_path, "index.pkl")
        with open(path, "wb") as handle:
            pickle.dump({"documents": []}, handle)
        vs = VectorStore.objects.create(base_path=self.vector_store_path)
        DocumentVector.objects.create(
            document=document,
            vectorstore=vs,
            vectorstore_location=path,
            document_location=document.extracted_text_path,
            status="ready",
            method="dense",
        )
        self.assertTrue(self.pipeline.is_initialized("alice"))

    def test_is_initialized_ignores_other_methods_indexes(self):
        # Each method keeps its own index; a sparse index must not make the
        # dense pipeline think it is ready.
        user = make_user()
        document = make_document(user)
        path = os.path.join(self.vector_store_path, "sparse.pkl")
        with open(path, "wb") as handle:
            pickle.dump({"documents": []}, handle)
        vs = VectorStore.objects.create(base_path=self.vector_store_path)
        DocumentVector.objects.create(
            document=document,
            vectorstore=vs,
            vectorstore_location=path,
            document_location=document.extracted_text_path,
            status="ready",
            method="sparse",
        )
        self.assertFalse(self.pipeline.is_initialized("alice"))


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, OPENROUTER_API_KEY="test-key")
class DensePipelineIndexTests(PipelineTestCase):
    """Dense: build, persist, reload."""

    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.document = make_document(self.user)
        self.pipeline = self.make_pipeline(DenseRAGPipeline)

    def test_build_index_writes_chunks_a_record_and_a_file(self):
        path = self.pipeline._build_index("alice", self.document)

        self.assertTrue(os.path.exists(path))
        self.assertEqual(Chunk.objects.filter(document=self.document).count(), 3)
        record = DocumentVector.objects.get(document=self.document, method="dense")
        self.assertEqual(record.vectorstore_location, path)
        self.assertEqual(record.status, "ready")
        self.assertEqual(len(self.pipeline.rag.documents), 3)

    def test_build_index_without_extracted_text_raises(self):
        self.document.extracted_text_path = ""
        self.document.save()
        with self.assertRaises(ValueError):
            self.pipeline._build_index("alice", self.document)

    def test_state_round_trip_restores_documents_vectors_and_metadata(self):
        path = self.pipeline._build_index("alice", self.document)

        reloaded = self.make_pipeline(DenseRAGPipeline)
        self.assertTrue(reloaded._load_state(path))
        self.assertEqual(reloaded.rag.documents, self.pipeline.rag.documents)
        self.assertEqual(
            reloaded.rag.document_metadata, self.pipeline.rag.document_metadata
        )
        np.testing.assert_allclose(
            np.asarray(reloaded.rag.document_vectors),
            np.asarray(self.pipeline.rag.document_vectors),
        )

    def test_load_state_returns_false_for_a_missing_or_corrupt_file(self):
        self.assertFalse(
            self.pipeline._load_state(os.path.join(self.vector_store_path, "nope.pkl"))
        )

        corrupt = os.path.join(self.vector_store_path, "corrupt.pkl")
        with open(corrupt, "wb") as handle:
            handle.write(b"not a pickle")
        self.assertFalse(self.pipeline._load_state(corrupt))

    def test_init_reuses_an_existing_index_instead_of_re_embedding(self):
        self.pipeline._build_index("alice", self.document)
        calls_after_build = self.pipeline.rag.client.embeddings.create.call_count

        fresh = self.make_pipeline(DenseRAGPipeline)
        self.assertTrue(fresh.init("alice"))

        self.assertEqual(fresh.rag.client.embeddings.create.call_count, 0)
        self.assertEqual(len(fresh.rag.documents), 3)
        self.assertGreater(calls_after_build, 0)
        self.assertEqual(
            DocumentVector.objects.filter(document=self.document, method="dense").count(),
            1,
        )

    def test_init_discards_a_record_whose_file_vanished_and_rebuilds(self):
        path = self.pipeline._build_index("alice", self.document)
        os.remove(path)
        stale_id = DocumentVector.objects.get(
            document=self.document, method="dense"
        ).pk

        fresh = self.make_pipeline(DenseRAGPipeline)
        self.assertTrue(fresh.init("alice"))

        self.assertFalse(DocumentVector.objects.filter(pk=stale_id).exists())
        record = DocumentVector.objects.get(document=self.document, method="dense")
        self.assertTrue(os.path.exists(record.vectorstore_location))

    def test_init_without_a_document_raises(self):
        with self.assertRaises(ValueError):
            self.pipeline.init("nobody")

    def test_init_job_reports_progress_while_building(self):
        job = Job.objects.create(user=self.user, document=self.document)
        seen = []
        original_save = Job.save

        def record_progress(self_job, *args, **kwargs):
            seen.append(self_job.progress)
            return original_save(self_job, *args, **kwargs)

        with mock.patch.object(Job, "save", record_progress):
            self.assertTrue(self.pipeline.init_job("alice", job=job))

        self.assertEqual(seen, [10, 20, 90])

    def test_init_job_shortcuts_to_80_when_an_index_already_exists(self):
        self.pipeline._build_index("alice", self.document)
        job = Job.objects.create(user=self.user, document=self.document)

        fresh = self.make_pipeline(DenseRAGPipeline)
        self.assertTrue(fresh.init_job("alice", job=job))

        job.refresh_from_db()
        self.assertEqual(job.progress, 80)

    def test_init_job_works_without_a_job_object(self):
        self.assertTrue(self.pipeline.init_job("alice"))


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, OPENROUTER_API_KEY="test-key")
class DensePipelineRunTests(PipelineTestCase):
    """Dense: query → retrieval → answer."""

    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.document = make_document(self.user)
        self.pipeline = self.make_pipeline(DenseRAGPipeline)
        self.pipeline._build_index("alice", self.document)

    def test_run_returns_the_answer_context_and_chunk_ids(self):
        self.pipeline.llm.prompt_generate.return_value = "alpha embeddings"

        result = self.pipeline.run("alice", "what about alpha?")

        self.assertEqual(result["answer"], "generated answer")
        self.assertIn("alpha", result["context"][0]["text"].lower())
        self.assertEqual(
            [c["chunk_id"] for c in result["context"]], result["chunk_ids"]
        )
        for entry in result["context"]:
            self.assertIn("score", entry)

    def test_run_never_leaks_the_internal_retrieved_docs_key(self):
        # `retrieved_docs` is an internal handoff to run_analysis; it must not
        # reach the API serializer.
        result = self.pipeline.run("alice", "alpha")
        self.assertNotIn("retrieved_docs", result)

    def test_the_optimized_query_is_what_gets_retrieved_and_generated_with(self):
        self.pipeline.llm.prompt_generate.return_value = "alpha embeddings"

        with mock.patch.object(
            self.pipeline.rag, "retrieve", wraps=self.pipeline.rag.retrieve
        ) as retrieve:
            self.pipeline.run("alice", "tell me about alpha")

        retrieve.assert_called_once_with("alpha embeddings")
        generated_query, context = self.pipeline.llm.rag_generate.call_args[0]
        self.assertEqual(generated_query, "alpha embeddings")
        self.assertIn("Alpha paragraph", context)

    def test_an_empty_optimized_query_result_retries_the_original(self):
        # A rewritten query can miss where the literal one hits; the retry is
        # what keeps a bad rewrite from emptying the answer.
        with mock.patch.object(
            self.pipeline.rag, "retrieve", side_effect=[[], [{"text": "t", "chunk_id": 1, "score": 0.4}]]
        ) as retrieve:
            result = self.pipeline.run("alice", "original question")

        self.assertEqual(retrieve.call_count, 2)
        self.assertEqual(retrieve.call_args_list[1][0][0], "original question")
        self.assertEqual(result["chunk_ids"], [1])

    def test_no_retrieval_at_all_still_answers_with_empty_context(self):
        with mock.patch.object(self.pipeline.rag, "retrieve", return_value=[]):
            result = self.pipeline.run("alice", "unanswerable")

        self.assertEqual(result["context"], [])
        self.assertEqual(result["chunk_ids"], [])
        self.pipeline.llm.rag_generate.assert_called_once_with(
            "unanswerable", context=""
        )

    def test_run_initializes_itself_when_memory_is_empty(self):
        cold = self.make_pipeline(DenseRAGPipeline)
        self.assertEqual(cold.rag.documents, [])

        result = cold.run("alice", "alpha")

        self.assertEqual(len(cold.rag.documents), 3)
        self.assertEqual(result["answer"], "generated answer")

    def test_run_for_a_user_without_documents_raises(self):
        with self.assertRaises(ValueError):
            self.pipeline.run("nobody", "alpha")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, OPENROUTER_API_KEY="test-key")
class DensePipelineAnalysisTests(PipelineTestCase):
    """Dense: run_analysis wiring against stored ground truth."""

    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.document = make_document(self.user)
        self.pipeline = self.make_pipeline(DenseRAGPipeline)
        self.pipeline._build_index("alice", self.document)
        self.conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            query="what about alpha?",
            response="",
            context="",
        )
        self.pipeline.llm.prompt_generate.return_value = "alpha embeddings"

        # The judge is an LLM call; its arithmetic is covered in
        # evaluation/tests.py, so here only the wiring matters.
        judge_patch = mock.patch(
            "pipeline.dense_rag_pipeline.evaluate_response",
            return_value={"rougeL_f1": 0.5, "faithfulness": 0.8},
        )
        self.judge = judge_patch.start()
        self.addCleanup(judge_patch.stop)

    def _alpha_chunk(self):
        return Chunk.objects.get(document=self.document, text__startswith="Alpha")

    def test_retrieval_metrics_are_scored_against_ground_truth_chunks(self):
        GroundTruthChunk.objects.create(
            conversation=self.conversation, chunk=self._alpha_chunk()
        )

        result = self.pipeline.run_analysis(self.document.pk, self.conversation.pk)

        chunk_eval = result["evaluation"]["chunk_evaluation"]
        self.assertEqual(chunk_eval["recall_k"], 1.0)
        self.assertGreater(chunk_eval["precision_k"], 0.0)
        self.assertLessEqual(chunk_eval["precision_k"], 1.0)

    def test_a_miss_scores_zero_rather_than_erroring(self):
        orphan_document = make_document(make_user("bob"), name="other.txt")
        orphan_chunk = Chunk.objects.create(
            document=orphan_document, text="unrelated", config_hash="x"
        )
        GroundTruthChunk.objects.create(
            conversation=self.conversation, chunk=orphan_chunk
        )

        result = self.pipeline.run_analysis(self.document.pk, self.conversation.pk)

        self.assertEqual(result["evaluation"]["chunk_evaluation"]["recall_k"], 0.0)
        self.assertEqual(result["evaluation"]["chunk_evaluation"]["f1_k"], 0.0)

    def test_answer_metrics_run_only_with_an_expected_answer(self):
        GroundTruthChunk.objects.create(
            conversation=self.conversation, chunk=self._alpha_chunk()
        )

        without = self.pipeline.run_analysis(self.document.pk, self.conversation.pk)
        self.assertEqual(without["evaluation"]["response_evaluation"], {})
        self.judge.assert_not_called()

        GroundTruthResponse.objects.create(
            conversation=self.conversation, response="Alpha is about embeddings."
        )
        with_expected = self.pipeline.run_analysis(
            self.document.pk, self.conversation.pk
        )

        self.assertEqual(
            with_expected["evaluation"]["response_evaluation"]["faithfulness"], 0.8
        )
        answer, expected = self.judge.call_args[0]
        self.assertEqual(answer, "generated answer")
        self.assertEqual(expected, "Alpha is about embeddings.")
        self.assertTrue(self.judge.call_args[1]["chunks"])

    def test_no_ground_truth_at_all_still_returns_scored_zeroes(self):
        result = self.pipeline.run_analysis(self.document.pk, self.conversation.pk)

        self.assertEqual(
            result["evaluation"]["chunk_evaluation"],
            {"precision_k": 0.0, "recall_k": 0.0, "f1_k": 0.0},
        )
        self.assertEqual(result["evaluation"]["response_evaluation"], {})

    def test_empty_retrieval_skips_evaluation_entirely(self):
        with mock.patch.object(self.pipeline.rag, "retrieve", return_value=[]):
            result = self.pipeline.run_analysis(
                self.document.pk, self.conversation.pk
            )

        self.assertEqual(result["evaluation"], {})
        self.assertNotIn("retrieved_docs", result)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, OPENROUTER_API_KEY="test-key")
class SparsePipelineTests(PipelineTestCase):
    """Sparse: BM25 indexing, persistence, and the same run contract."""

    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.document = make_document(self.user)
        self.pipeline = self.make_pipeline(SparseRAGPipeline)

    def test_build_index_creates_a_bm25_index_and_a_record(self):
        path = self.pipeline._build_index("alice", self.document)

        self.assertTrue(os.path.exists(path))
        self.assertIsNotNone(self.pipeline.rag.bm25)
        self.assertEqual(len(self.pipeline.rag.documents), 3)
        DocumentVector.objects.get(document=self.document, method="sparse")

    def test_keyword_query_retrieves_the_matching_chunk(self):
        self.pipeline._build_index("alice", self.document)

        results = self.pipeline.rag.retrieve("reranking")

        self.assertTrue(results)
        self.assertIn("Gamma", results[0]["text"])
        self.assertGreater(results[0]["score"], 0.0)
        self.assertIsNotNone(results[0]["chunk_id"])

    def test_a_query_matching_nothing_returns_no_chunks(self):
        # BM25 drops zero-scoring documents, which is what makes the
        # retry-with-the-original-query path in _run_core reachable.
        self.pipeline._build_index("alice", self.document)
        self.assertEqual(self.pipeline.rag.retrieve("zzzz nonexistent"), [])

    def test_state_round_trip_keeps_the_index_queryable(self):
        path = self.pipeline._build_index("alice", self.document)

        reloaded = self.make_pipeline(SparseRAGPipeline)
        self.assertTrue(reloaded._load_state(path))
        self.assertEqual(reloaded.rag.documents, self.pipeline.rag.documents)
        self.assertIn("Beta", reloaded.rag.retrieve("keyword")[0]["text"])

    def test_load_state_returns_false_for_a_corrupt_file(self):
        corrupt = os.path.join(self.vector_store_path, "corrupt.pkl")
        with open(corrupt, "wb") as handle:
            handle.write(b"nope")
        self.assertFalse(self.pipeline._load_state(corrupt))

    def test_run_initializes_then_answers(self):
        self.pipeline._build_index("alice", self.document)
        self.pipeline.llm.prompt_generate.return_value = "keyword search"

        cold = self.make_pipeline(SparseRAGPipeline)
        result = cold.run("alice", "tell me about keyword search")

        self.assertEqual(result["answer"], "generated answer")
        self.assertIn("Beta", result["context"][0]["text"])
        self.assertNotIn("retrieved_docs", result)

    def test_run_analysis_scores_against_ground_truth(self):
        self.pipeline._build_index("alice", self.document)
        conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            query="keyword search",
            response="",
            context="",
        )
        beta = Chunk.objects.get(document=self.document, text__startswith="Beta")
        GroundTruthChunk.objects.create(conversation=conversation, chunk=beta)
        self.pipeline.llm.prompt_generate.return_value = "keyword search"

        with mock.patch(
            "pipeline.sparse_rag_pipeline.evaluate_response",
            return_value={"rougeL_f1": 0.25},
        ):
            result = self.pipeline.run_analysis(self.document.pk, conversation.pk)

        self.assertEqual(result["evaluation"]["chunk_evaluation"]["recall_k"], 1.0)
        self.assertEqual(result["evaluation"]["response_evaluation"], {})

    def test_init_job_reports_progress(self):
        job = Job.objects.create(user=self.user, document=self.document)
        self.assertTrue(self.pipeline.init_job("alice", job=job))
        job.refresh_from_db()
        self.assertEqual(job.progress, 90)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, OPENROUTER_API_KEY="test-key")
class HybridPipelineTests(PipelineTestCase):
    """Hybrid: two engines, one reranked answer, and a stricter state guard."""

    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.document = make_document(self.user)
        self.pipeline = self.make_pipeline(HybridRAGPipeline)

    def test_build_index_populates_both_sub_engines(self):
        path = self.pipeline._build_index("alice", self.document)

        self.assertTrue(os.path.exists(path))
        self.assertEqual(len(self.pipeline.rag.sparse_engine.documents), 3)
        self.assertEqual(len(self.pipeline.rag.dense_engine.documents), 3)
        DocumentVector.objects.get(document=self.document, method="hybrid")

    def test_save_state_refuses_to_write_an_empty_index(self):
        # Writing an empty pickle used to produce a "ready" DocumentVector
        # pointing at nothing, which only failed later at query time.
        path = os.path.join(self.vector_store_path, "empty.pkl")
        with self.assertRaises(RuntimeError):
            self.pipeline._save_state(path)
        self.assertFalse(os.path.exists(path))

    def test_state_round_trip_restores_both_engines(self):
        path = self.pipeline._build_index("alice", self.document)

        reloaded = self.make_pipeline(HybridRAGPipeline)
        self.assertTrue(reloaded._load_state(path))
        self.assertEqual(len(reloaded.rag.sparse_engine.documents), 3)
        self.assertEqual(len(reloaded.rag.dense_engine.documents), 3)
        self.assertIsNotNone(reloaded.rag.sparse_engine.bm25)

    def test_a_pickle_without_bm25_is_rebuilt_from_the_tokenized_corpus(self):
        path = self.pipeline._build_index("alice", self.document)
        with open(path, "rb") as handle:
            data = pickle.load(handle)
        data["sparse"]["bm25"] = None
        with open(path, "wb") as handle:
            pickle.dump(data, handle)

        reloaded = self.make_pipeline(HybridRAGPipeline)
        self.assertTrue(reloaded._load_state(path))
        self.assertIsNotNone(reloaded.rag.sparse_engine.bm25)

    def test_an_incomplete_pickle_is_rejected(self):
        path = self.pipeline._build_index("alice", self.document)
        with open(path, "rb") as handle:
            data = pickle.load(handle)
        data["dense"]["vectors"] = []
        with open(path, "wb") as handle:
            pickle.dump(data, handle)

        reloaded = self.make_pipeline(HybridRAGPipeline)
        self.assertFalse(reloaded._load_state(path))

    def test_the_cross_encoder_decides_the_final_order(self):
        self.pipeline._build_index("alice", self.document)
        # Both keywords retrieve, from both sub-engines, so the candidate pool
        # holds alpha and beta and the only thing left to decide the order is
        # the reranker — which scores alpha highest.
        self.pipeline.llm.prompt_generate.return_value = "alpha beta"

        result = self.pipeline.run("alice", "anything")

        texts = [entry["text"] for entry in result["context"]]
        self.assertIn("Alpha", texts[0])
        self.assertTrue(any("Beta" in text for text in texts))
        self.assertEqual(len(result["context"]), self.pipeline.rag.final_top_k)
        self.assertNotIn("retrieved_docs", result)

    def test_run_initializes_from_disk_when_memory_is_empty(self):
        self.pipeline._build_index("alice", self.document)

        cold = self.make_pipeline(HybridRAGPipeline)
        result = cold.run("alice", "alpha")

        self.assertEqual(len(cold.rag.dense_engine.documents), 3)
        self.assertEqual(result["answer"], "generated answer")

    def test_run_analysis_scores_the_reranked_chunks(self):
        self.pipeline._build_index("alice", self.document)
        conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            query="alpha",
            response="",
            context="",
        )
        alpha = Chunk.objects.get(document=self.document, text__startswith="Alpha")
        GroundTruthChunk.objects.create(conversation=conversation, chunk=alpha)
        GroundTruthResponse.objects.create(
            conversation=conversation, response="Alpha is about embeddings."
        )
        self.pipeline.llm.prompt_generate.return_value = "alpha"

        with mock.patch(
            "pipeline.hybrid_rag_pipeline.evaluate_response",
            return_value={"rougeL_f1": 0.3, "faithfulness": 0.6},
        ):
            result = self.pipeline.run_analysis(self.document.pk, conversation.pk)

        self.assertEqual(result["evaluation"]["chunk_evaluation"]["recall_k"], 1.0)
        self.assertEqual(
            result["evaluation"]["response_evaluation"]["faithfulness"], 0.6
        )

    def test_init_job_reports_progress(self):
        job = Job.objects.create(user=self.user, document=self.document)
        self.assertTrue(self.pipeline.init_job("alice", job=job))
        job.refresh_from_db()
        self.assertEqual(job.progress, 90)


class RagRegistryTests(TestCase):
    """The method × model matrix, and the lookups the tasks make against it."""

    def _fresh_registry(self, **env):
        original = rag_service.RAGRegistry._instance
        rag_service.RAGRegistry._instance = None
        self.addCleanup(
            setattr, rag_service.RAGRegistry, "_instance", original
        )
        with mock.patch.dict(os.environ, env):
            return rag_service.RAGRegistry()

    def test_the_registry_is_a_singleton(self):
        first = self._fresh_registry(RAG_DISABLE_ENGINE_INIT="1")
        self.assertIs(first, rag_service.RAGRegistry())

    def test_disable_flag_skips_engine_construction(self):
        # This is what makes the whole suite runnable without API keys or
        # model downloads.
        registry = self._fresh_registry(RAG_DISABLE_ENGINE_INIT="1")
        self.assertEqual(registry.engines, {})

    def test_every_model_gets_every_method(self):
        with mock.patch.multiple(
            rag_service,
            DenseRAGPipeline=mock.DEFAULT,
            SparseRAGPipeline=mock.DEFAULT,
            HybridRAGPipeline=mock.DEFAULT,
        ):
            registry = self._fresh_registry(RAG_DISABLE_ENGINE_INIT="")

        self.assertEqual(len(registry.engines), 3)
        for methods in registry.engines.values():
            self.assertEqual(
                sorted(methods),
                ["Dense Retrieval", "Hybrid Retrieval", "Sparse Retrieval"],
            )

    def test_one_broken_engine_does_not_stop_the_others(self):
        with mock.patch.multiple(
            rag_service,
            DenseRAGPipeline=mock.Mock(side_effect=RuntimeError("no api key")),
            SparseRAGPipeline=mock.DEFAULT,
            HybridRAGPipeline=mock.DEFAULT,
        ):
            registry = self._fresh_registry(RAG_DISABLE_ENGINE_INIT="")

        for methods in registry.engines.values():
            self.assertNotIn("Dense Retrieval", methods)
            self.assertIn("Sparse Retrieval", methods)

    def test_get_engine_returns_the_registered_pipeline(self):
        registry = self._fresh_registry(RAG_DISABLE_ENGINE_INIT="1")
        sentinel = object()
        registry.engines = {"openai/gpt-4o-mini": {"Dense Retrieval": sentinel}}

        self.assertIs(
            registry.get_engine("Dense Retrieval", "openai/gpt-4o-mini"), sentinel
        )

    def test_get_engine_error_names_what_is_available(self):
        registry = self._fresh_registry(RAG_DISABLE_ENGINE_INIT="1")
        registry.engines = {"openai/gpt-4o-mini": {"Dense Retrieval": object()}}

        with self.assertRaises(ValueError) as ctx:
            registry.get_engine("Sparse Retrieval", "openai/gpt-4o-mini")
        self.assertIn("Dense Retrieval", str(ctx.exception))

        with self.assertRaises(ValueError):
            registry.get_engine("Dense Retrieval", "unknown/model")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class DataLoaderLoadTests(TestCase):
    """`DataLoader.load` — the first call in every _build_index()."""

    def test_load_reads_extracted_text_from_storage(self):
        path = default_storage.save(
            "documents/user_alice/extracted.txt", ContentFile("hello world")
        )
        self.assertEqual(DataLoader().load(path), "hello world")

    def test_load_rejects_an_unsupported_extension(self):
        with self.assertRaises(ValueError):
            DataLoader().load("documents/user_alice/notes.docx")
