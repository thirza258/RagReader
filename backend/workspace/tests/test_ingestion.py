"""Staged ingestion, checkpointed embeddings and job/document status (PRD §9, §41)."""
from datetime import timedelta
from unittest import mock

import numpy as np
from django.utils import timezone

import router.tasks as router_tasks
from common.errors import PipelineError
from evaluation.models import Chunk
from hybrid_rag.hybrid_rag import HybridRAG
from router.models import Document, DocumentVector, Job
from workspace.models import EmbeddingCacheEntry
from workspace.services import ingestion
from workspace.services.embedding_cache import EmbeddingCache
from workspace.services.ingestion import IngestionRunner, run_ingestion
from workspace.tests.helpers import WorkspaceTestCase, build_pdf, keyword_vector

SIX_PARAGRAPHS = "\n\n".join(
    f"{word.capitalize()} paragraph number {i} about retrieval."
    for i, word in enumerate(("alpha", "beta", "gamma", "delta", "epsilon", "zeta"), 1)
)


class StageRecorder:
    def __init__(self, test):
        self.statuses = []
        original = IngestionRunner._advance

        def spy(runner, status, *args, **kwargs):
            self.statuses.append(str(status))
            return original(runner, status, *args, **kwargs)

        patcher = mock.patch.object(IngestionRunner, "_advance", autospec=True, side_effect=spy)
        patcher.start()
        test.addCleanup(patcher.stop)


class IngestionStageTests(WorkspaceTestCase):
    def test_stages_progress_to_ready_with_index_pages_and_positions(self):
        recorder = StageRecorder(self)
        # Each page is longer than half the 60-character chunk size, so each
        # becomes its own chunk.
        pdf = build_pdf(["Alpha page about dense embeddings and vectors.", "Beta page about keyword search with BM25.",
                         "Gamma page about cross-encoder reranking."])
        with self.captureOnCommitCallbacks(execute=True):
            body = self.upload("paper.pdf", pdf).json()
        status = self.get(f"/api/v1/documents/{body['id']}/ingestion/").json()
        self.assertEqual(status["status"], "QUEUED")
        self.assertEqual([stage["state"] for stage in status["stages"]], ["done"] + ["pending"] * 5)
        self.assertFalse(status["can_retry"])
        self.assertEqual(status["job"]["status"], "PENDING")

        self.assertTrue(self.ingest_last_queued())
        self.assertEqual(recorder.statuses, ["EXTRACTING", "CLEANING", "CHUNKING", "EMBEDDING", "INDEXING"])

        document = Document.objects.select_related("current_index").get(pk=body["id"])
        self.assertEqual((document.status, document.progress, document.status_detail), ("READY", 100, "Ready"))
        self.assertIsNotNone(document.ingested_at)
        vector = document.current_index
        self.assertEqual((vector.method, vector.status), ("dense", "ready"))
        self.assertEqual(document.metadata["page_count"], 3)
        self.assertEqual([page["number"] for page in document.metadata["pages"]], [1, 2, 3])
        self.assertEqual(document.metadata["chunk_count"], 3)
        self.assertEqual(document.metadata["embedding_model"], "openai/text-embedding-3-small")
        self.assertEqual(document.metadata["chunk_config"]["strategy"], "paragraph")
        self.assertEqual(Job.objects.get(document=document).status, "READY")

        status = self.get(f"/api/v1/documents/{body['id']}/ingestion/").json()
        self.assertEqual([stage["state"] for stage in status["stages"]], ["done"] * 6)
        self.assertEqual([stage["id"] for stage in status["stages"]],
                         ["UPLOADING", "EXTRACTING", "CLEANING", "CHUNKING", "EMBEDDING", "INDEXING"])
        self.assertTrue(status["can_retry"])

        text = self.get(f"/api/v1/documents/{body['id']}/text/").json()["text"]
        chunks = sorted(Chunk.objects.filter(document=document), key=lambda row: row.metadata["ordinal"])
        self.assertEqual([row.metadata["page_start"] for row in chunks], [1, 2, 3])
        for row in chunks:
            meta = row.metadata
            self.assertEqual(text[meta["char_start"]:meta["char_end"]], row.text)
            self.assertEqual(meta["page_start"], meta["page_end"])
            self.assertEqual(meta["strategy"], "paragraph")  # merged, not replaced

    def test_progress_is_visible_per_embedding_batch(self):
        details = []
        original = IngestionRunner._write

        def spy(runner, progress, detail, **kwargs):
            details.append((progress, detail))
            return original(runner, progress, detail, **kwargs)

        with mock.patch.object(ingestion, "EMBEDDING_BATCH_SIZE", 2), \
                mock.patch.object(IngestionRunner, "_write", autospec=True, side_effect=spy):
            self.ready_text_document(SIX_PARAGRAPHS)
        embedding = [detail for progress, detail in details if detail.startswith("Embedded")]
        self.assertEqual(embedding, ["Embedded 0 of 6 chunks", "Embedded 2 of 6 chunks",
                                     "Embedded 4 of 6 chunks", "Embedded 6 of 6 chunks"])
        progresses = [progress for progress, _ in details]
        self.assertEqual(progresses, sorted(progresses))

    def test_build_index_reuses_checkpointed_vectors_instead_of_the_provider(self):
        document = self.ready_text_document(SIX_PARAGRAPHS)
        texts = self.embeddings.embedded_texts
        self.assertEqual(len(texts), 6)  # each chunk embedded exactly once, in EMBEDDING
        self.assertEqual(EmbeddingCacheEntry.objects.filter(document_id=document["id"]).count(), 6)
        cached = EmbeddingCache(document["id"], "openai/text-embedding-3-small").lookup(texts)
        np.testing.assert_allclose(cached[texts[0]], keyword_vector(texts[0]), rtol=1e-6)

    def test_failure_at_embedding_records_the_stage(self):
        self.embeddings.fail_on_call = 1
        self.embeddings.error = PipelineError("provider_timeout", "Embedding timed out. Try again.", retryable=True, http_status=504)
        document = self.add_text(SIX_PARAGRAPHS)
        self.assertFalse(self.ingest_last_queued())
        body = self.get(f"/api/v1/documents/{document['id']}/").json()
        self.assertEqual(body["status"], "FAILED")
        self.assertEqual(body["error"], {"code": "provider_timeout", "message": "Embedding timed out. Try again.",
                                         "retryable": True, "stage": "EMBEDDING"})
        job = Job.objects.get(document_id=document["id"])
        self.assertEqual((job.status, job.error_code, job.retryable), ("FAILED", "provider_timeout", True))
        status = self.get(f"/api/v1/documents/{document['id']}/ingestion/").json()
        self.assertEqual([stage["state"] for stage in status["stages"]], ["done", "done", "done", "done", "failed", "pending"])
        self.assertTrue(status["can_retry"])

    def test_unexpected_errors_are_generic_and_retryable(self):
        with mock.patch.object(ingestion.extraction, "clean_pages", side_effect=RuntimeError("PRIVATE stack detail")):
            document = self.add_text("Alpha")
            self.assertFalse(self.ingest_last_queued())
        error = self.get(f"/api/v1/documents/{document['id']}/").json()["error"]
        self.assertEqual((error["code"], error["stage"], error["retryable"]), ("ingestion_failed", "CLEANING", True))
        self.assertNotIn("PRIVATE", error["message"])

    def test_a_document_without_text_fails_without_retry(self):
        with self.captureOnCommitCallbacks(execute=True):
            body = self.upload("scan.pdf", build_pdf(["", ""])).json()
        self.assertFalse(self.ingest_last_queued())
        error = self.get(f"/api/v1/documents/{body['id']}/").json()["error"]
        self.assertEqual((error["code"], error["retryable"], error["stage"]), ("no_extractable_text", False, "CLEANING"))


class ResumeTests(WorkspaceTestCase):
    def test_retry_after_a_mid_embedding_failure_embeds_only_what_is_missing(self):
        self.embeddings.fail_on_call = 2
        self.embeddings.error = PipelineError("provider_unavailable", "OpenRouter could not complete it.", retryable=True)
        with mock.patch.object(ingestion, "EMBEDDING_BATCH_SIZE", 2):
            document = self.add_text(SIX_PARAGRAPHS)
            self.assertFalse(self.ingest_last_queued())
            first_run = list(self.embeddings.embedded_texts)
            self.assertEqual(len(first_run), 4)  # batch 1 committed, batch 2 failed
            self.assertEqual(EmbeddingCacheEntry.objects.filter(document_id=document["id"]).count(), 2)
            self.assertEqual(self.get(f"/api/v1/documents/{document['id']}/").json()["status"], "FAILED")

            self.embeddings.fail_on_call = None
            self.embeddings.calls.clear()
            with self.captureOnCommitCallbacks(execute=True):
                retried = self.post(f"/api/v1/documents/{document['id']}/ingestion/")
            self.assertEqual(retried.status_code, 202)
            self.assertEqual((retried.json()["status"], retried.json()["can_retry"]), ("QUEUED", False))
            self.assertTrue(self.ingest_last_queued())

        second_run = self.embeddings.embedded_texts
        self.assertEqual(len(second_run), 4)  # the 4 texts never committed, nothing else
        self.assertFalse(set(second_run) & set(first_run[:2]))
        self.assertEqual(self.get(f"/api/v1/documents/{document['id']}/").json()["status"], "READY")
        self.assertEqual(Job.objects.filter(document_id=document["id"]).count(), 2)

    def test_reindexing_a_ready_document_reuses_every_vector(self):
        document = self.ready_text_document(SIX_PARAGRAPHS)
        first_index = Document.objects.get(pk=document["id"]).current_index_id
        self.embeddings.calls.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.post(f"/api/v1/documents/{document['id']}/ingestion/").status_code, 202)
        self.assertTrue(self.ingest_last_queued())
        self.assertEqual(self.embeddings.calls, [])
        reindexed = Document.objects.get(pk=document["id"])
        self.assertEqual(reindexed.status, "READY")
        self.assertNotEqual(reindexed.current_index_id, first_index)

    def test_retry_is_refused_while_a_job_is_live(self):
        document = self.add_text("Alpha")
        response = self.post(f"/api/v1/documents/{document['id']}/ingestion/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "ingestion_in_progress")
        self.assertEqual(Job.objects.filter(document_id=document["id"]).count(), 1)


class JobProtocolTests(WorkspaceTestCase):
    def test_duplicate_delivery_does_nothing(self):
        document = self.ready_text_document("Alpha paragraph.")
        job_id = self.delay.call_args.args[0]
        calls, vectors = len(self.embeddings.calls), DocumentVector.objects.count()
        self.get_engine.reset_mock()
        self.assertTrue(run_ingestion(job_id))  # READY: nothing to do
        Job.objects.filter(pk=job_id).update(status=Job.Status.PROCESSING)
        self.assertFalse(run_ingestion(job_id))  # owned by another worker: nothing to do
        self.get_engine.assert_not_called()
        self.assertEqual((len(self.embeddings.calls), DocumentVector.objects.count()), (calls, vectors))
        self.assertEqual(Document.objects.get(pk=document["id"]).status, "READY")
        self.assertFalse(run_ingestion("00000000-0000-0000-0000-000000000000"))
        self.assertFalse(run_ingestion("not-a-uuid"))

    def test_stalled_job_fails_the_document_when_read(self):
        document = self.add_text("Alpha")
        job = Job.objects.get(document_id=document["id"])
        Job.objects.filter(pk=job.pk).update(status=Job.Status.PROCESSING, updated_at=timezone.now() - timedelta(minutes=40))
        Document.objects.filter(pk=document["id"]).update(status=Document.Status.EMBEDDING)
        body = self.get(f"/api/v1/documents/{document['id']}/").json()
        self.assertEqual(body["status"], "FAILED")
        self.assertEqual((body["error"]["code"], body["error"]["stage"], body["error"]["retryable"]),
                         ("ingestion_timeout", "EMBEDDING", True))
        listed = self.get("/api/v1/documents/").json()["results"][0]
        self.assertEqual(listed["status"], "FAILED")
        self.assertTrue(self.get(f"/api/v1/documents/{document['id']}/ingestion/").json()["can_retry"])

    def test_a_run_that_lost_its_job_stops_without_writing(self):
        document = self.add_text(SIX_PARAGRAPHS)
        job_id = self.delay.call_args.args[0]

        def expire(*args, **kwargs):
            Job.objects.filter(pk=job_id).update(status=Job.Status.FAILED, error_code="ingestion_timeout")
            return ["chunk"]

        with mock.patch.object(self.pipeline.chunker, "chunk", side_effect=expire):
            self.assertFalse(run_ingestion(job_id))
        stored = Document.objects.get(pk=document["id"])
        self.assertEqual(stored.status, "CHUNKING")  # the stage it was in; nothing after it
        self.assertEqual(self.embeddings.calls, [])
        self.assertEqual(self.get(f"/api/v1/documents/{document['id']}/").json()["status"], "FAILED")


class LegacyInitializationTests(WorkspaceTestCase):
    def legacy_document(self):
        from router.models import GuestUser
        self.post("/api/v1/insert-text/", {"USER": self.user.username, "TEXT": "Alpha legacy text."})
        return Document.objects.filter(user=GuestUser.objects.get(pk=self.user.pk)).latest("created_at")

    def test_legacy_insert_assigns_the_default_workspace(self):
        document = self.legacy_document()
        default = self.get("/api/v1/workspaces/").json()["results"][0]
        self.assertEqual(document.workspace_id, default["id"])
        self.assertEqual(self.get("/api/v1/documents/").json()["results"][0]["id"], document.pk)

    def test_initialize_rag_task_keeps_the_document_status_in_step(self):
        document = self.legacy_document()
        job = Job.objects.create(user=self.user, document=document)
        statuses = []

        def init_job(username, job=None):
            statuses.append(Document.objects.get(pk=document.pk).status)
            self.pipeline._build_index(username, document)
            return True

        engine = mock.Mock(init_job=mock.Mock(side_effect=init_job))
        with mock.patch.object(router_tasks.rag_registry, "get_engine", return_value=engine):
            self.assertTrue(router_tasks.initialize_rag_task(str(job.pk), self.user.username, "Dense Retrieval", "openai/gpt-4o-mini"))
        self.assertEqual(statuses, ["CHUNKING"])
        document.refresh_from_db()
        self.assertEqual(document.status, "READY")
        self.assertEqual(document.current_index, DocumentVector.objects.get(document=document, method="dense"))
        self.assertEqual(self.get(f"/api/v1/documents/{document.pk}/").json()["index"]["id"], document.current_index_id)

    def test_initialize_rag_task_failure_fails_the_document(self):
        document = self.legacy_document()
        job = Job.objects.create(user=self.user, document=document)
        engine = mock.Mock(init_job=mock.Mock(side_effect=PipelineError("provider_timeout", "Embedding timed out.", retryable=True)))
        with mock.patch.object(router_tasks.rag_registry, "get_engine", return_value=engine):
            self.assertFalse(router_tasks.initialize_rag_task(str(job.pk), self.user.username, "Dense Retrieval", "openai/gpt-4o-mini"))
        body = self.get(f"/api/v1/documents/{document.pk}/").json()
        self.assertEqual((body["status"], body["error"]["code"], body["error"]["retryable"]), ("FAILED", "provider_timeout", True))


class EngineCacheParameterTests(WorkspaceTestCase):
    def test_hybrid_index_documents_passes_the_cache_to_its_dense_half(self):
        hybrid = HybridRAG.__new__(HybridRAG)
        hybrid.sparse_engine, hybrid.dense_engine = mock.Mock(), mock.Mock()
        cache = object()
        hybrid.index_documents([{"text": "alpha", "chunk_id": 1}], embedding_cache=cache)
        self.assertIs(hybrid.dense_engine.index_documents.call_args.kwargs["embedding_cache"], cache)

    def test_dense_index_documents_embeds_only_cache_misses(self):
        rag = self.pipeline.rag
        cache = mock.Mock(lookup=mock.Mock(return_value={"alpha one": np.array(keyword_vector("alpha one"))}))
        rag.index_documents([{"text": "alpha one", "chunk_id": 1}, {"text": "beta two", "chunk_id": 2},
                             {"text": "alpha one", "chunk_id": 1}], embedding_cache=cache)
        self.assertEqual(self.embeddings.calls, [["beta two"]])
        self.assertEqual(rag.document_vectors.shape, (3, len(keyword_vector(""))))


class LegacyGroundTruthTests(WorkspaceTestCase):
    """Re-indexing must not cost a legacy document its deep-analysis ground truth."""

    RAW = "Alpha legacy line one\nAlpha legacy line two continues here.\n\nBeta second paragraph of the legacy text."

    def legacy_indexed_document(self):
        self.post("/api/v1/insert-text/", {"USER": self.user.username, "TEXT": self.RAW})
        document = Document.objects.filter(user=self.user).latest("created_at")
        self.pipeline._build_index(self.user.username, document)  # what open-chat initialization did
        return document

    def reindex(self, document):
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.post(f"/api/v1/documents/{document.pk}/ingestion/").status_code, 202)
        self.assertTrue(self.ingest_last_queued())

    def test_ground_truth_keeps_the_legacy_text_and_chunks(self):
        from evaluation.models import GroundTruthChunk
        from router.models import Conversation
        document = self.legacy_indexed_document()
        before = list(Chunk.objects.filter(document=document).order_by("pk").values_list("pk", "text"))
        turn = Conversation.objects.create(user=self.user, document=document, query="alpha?", response="", context="")
        GroundTruthChunk.objects.create(conversation=turn, chunk_id=before[0][0])

        self.reindex(document)

        self.assertEqual(list(Chunk.objects.filter(document=document).order_by("pk").values_list("pk", "text")), before)
        self.assertTrue(GroundTruthChunk.objects.filter(conversation=turn, chunk_id=before[0][0]).exists())
        self.assertEqual(self.get(f"/api/v1/documents/{document.pk}/").json()["status"], "READY")
        text = self.get(f"/api/v1/documents/{document.pk}/text/").json()["text"]
        self.assertEqual(text, self.RAW)
        for row in Chunk.objects.filter(document=document):
            self.assertEqual(text[row.metadata["char_start"]:row.metadata["char_end"]], row.text)

    def test_without_ground_truth_the_document_is_re_extracted(self):
        document = self.legacy_indexed_document()
        self.reindex(document)
        text = self.get(f"/api/v1/documents/{document.pk}/text/").json()["text"]
        self.assertEqual(text, "Alpha legacy line one Alpha legacy line two continues here.\n\nBeta second paragraph of the legacy text.")
        self.assertEqual(Document.objects.get(pk=document.pk).metadata["text_source"], "extracted")
