"""Staged background ingestion (PRD §9, §41) and its bookkeeping.

    QUEUED → EXTRACTING → CLEANING → CHUNKING → EMBEDDING → INDEXING → READY

Every stage writes the document's status and the job's heartbeat *outside*
any transaction, so the API (another connection) sees progress live and the
stall detector (`Job.expire_if_stalled`) never expires a run that is moving.
The only transaction is `_build_index`'s own, which stays atomic: a failed
build leaves the previous chunks, ground truth and indexes untouched.

Embeddings are checkpointed batch by batch in EmbeddingCacheEntry, so a retry
resumes where the failure happened instead of starting from chunk 0.
"""
import logging
from uuid import UUID

from celery.exceptions import SoftTimeLimitExceeded
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from common.constant import DEFAULT_CHAT_VARIANT
from common.embeddings import EMBEDDING_BATCH_SIZE, embed_texts
from common.errors import PipelineError, error_payload
from evaluation.models import Chunk, GroundTruthChunk
from rag.rag_service import engine_execution, rag_registry
from router.models import Document, DocumentVector, Job
from utils.insert_file import DataLoader
from workspace.services import extraction
from workspace.services.embedding_cache import EmbeddingCache
from workspace.services.positions import chunk_positions
from workspace.services.uploads import delete_storage_path, directory_of, document_directory

logger = logging.getLogger(__name__)

Status = Document.Status
TERMINAL = {Status.READY, Status.FAILED}
WORKER_STAGES = {Status.EXTRACTING, Status.CLEANING, Status.CHUNKING, Status.EMBEDDING, Status.INDEXING}
STAGE_LABELS = {
    Status.EXTRACTING: "text extraction",
    Status.CLEANING: "cleaning",
    Status.CHUNKING: "chunking",
    Status.EMBEDDING: "embedding",
    Status.INDEXING: "indexing",
}
# Progress bands per stage (PRD §9 checklist; docs/prd-implementation.md).
EMBEDDING_START, EMBEDDING_END = 25, 85
QUEUE_FAILURE_MESSAGE = "The ingestion worker could not be reached. Try again shortly."


class IngestionAborted(Exception):
    """This run no longer owns its job (expired or superseded); stop quietly."""


def chat_engine():
    """The engine whose chunker and embeddings the chat path answers with."""
    return rag_registry.get_engine(DEFAULT_CHAT_VARIANT["method"], DEFAULT_CHAT_VARIANT["model"])


def dense_engine_of(engine):
    rag = engine.rag
    return getattr(rag, "dense_engine", rag)


# ── Job bookkeeping (API side) ───────────────────────────────────────────────

def latest_job(document):
    return Job.objects.filter(document=document).order_by("-created_at").first()


def live_job(document):
    job = latest_job(document)
    if job is not None:
        job.expire_if_stalled()
    if job is not None and job.status in (Job.Status.PENDING, Job.Status.PROCESSING):
        return job
    return None


def refresh_document_status(document):
    """Fail a non-terminal document whose job failed or stalled.

    A worker that was killed never writes its failure, so the document would
    show "Embedding…" forever; reading it is when that gets noticed.
    """
    if document.status in TERMINAL:
        return document
    job = latest_job(document)
    if job is None:
        return document
    job.expire_if_stalled()
    if job.status == Job.Status.FAILED:
        stage = document.status if document.status in WORKER_STAGES else ""
        Document.objects.filter(pk=document.pk, status=document.status).update(
            status=Status.FAILED, error_stage=stage,
            error_code=job.error_code or "ingestion_failed",
            error_message=job.error_message or "Document ingestion failed. Retry ingestion.",
            retryable=job.retryable, status_detail=_failed_detail(stage), updated_at=timezone.now(),
        )
        document.refresh_from_db()
    return document


def _failed_detail(stage):
    label = STAGE_LABELS.get(stage)
    return f"Failed during {label}" if label else "Failed"


def queue_ingestion(document, failures):
    """Create an ingest job for `document` and enqueue it once committed.

    Call inside `transaction.atomic()`. If the broker cannot be reached the
    job and document are failed (retryable) and the error is appended to
    `failures`, so the view can answer 503 with the document.
    """
    job = Job.objects.create(user_id=document.user_id, document=document, kind=Job.Kind.INGEST)
    Document.objects.filter(pk=document.pk).update(
        status=Status.QUEUED, progress=0, status_detail="Waiting for a worker",
        error_stage="", error_code="", error_message="", retryable=False, updated_at=timezone.now(),
    )

    def enqueue():
        from workspace import tasks
        try:
            tasks.ingest_document_task.delay(str(job.pk))
        except Exception:
            failure = PipelineError("job_queue_unavailable", QUEUE_FAILURE_MESSAGE, retryable=True, http_status=503)
            job.mark_failed(str(failure), failure.code, failure.retryable)
            Document.objects.filter(pk=document.pk).update(
                status=Status.FAILED, error_stage="", error_code=failure.code, error_message=str(failure),
                retryable=True, status_detail="Failed", updated_at=timezone.now(),
            )
            failures.append(failure)
            logger.warning("Could not enqueue ingestion job %s", job.pk, exc_info=True)

    transaction.on_commit(enqueue)
    return job


# ── Worker ───────────────────────────────────────────────────────────────────

def run_ingestion(job_id):
    """Body of workspace.tasks.ingest_document_task. Returns True when READY."""
    try:
        job = Job.objects.select_related("user", "document", "document__user").get(pk=UUID(str(job_id)))
    except (Job.DoesNotExist, ValueError):
        logger.warning("Ingestion job %s does not exist", job_id)
        return False
    if job.status == Job.Status.READY:
        return True
    # A duplicate delivery must not start a second extraction/embedding run.
    claimed = Job.objects.filter(pk=job.pk, status=Job.Status.PENDING).update(
        status=Job.Status.PROCESSING, progress=1, updated_at=timezone.now(),
    )
    if not claimed:
        return False
    job.refresh_from_db()
    if job.document is None:
        job.mark_failed("The ingestion job has no document.", "missing_document", False)
        return False
    runner = IngestionRunner(job)
    try:
        runner.run()
        return True
    except IngestionAborted:
        logger.info("Ingestion job %s lost ownership; stopping without writing", job.pk)
        return False
    except Exception as exc:
        logger.warning("Ingestion failed for job %s at %s", job.pk, runner.stage, exc_info=True)
        if isinstance(exc, SoftTimeLimitExceeded):
            exc = PipelineError(
                "ingestion_timeout",
                "Ingestion took longer than the 30-minute limit. Retry to resume from the saved embeddings.",
                retryable=True, http_status=504,
            )
        error = error_payload(exc, code="ingestion_failed",
                              message="Document ingestion failed. Retry ingestion; if it keeps failing, check the server logs.")
        # Only the run that still owns the job may report its failure.
        if Job.objects.filter(pk=job.pk, status=Job.Status.PROCESSING).exists():
            job.mark_failed(error["error"], error["error_code"], error["retryable"])
            Document.objects.filter(pk=job.document_id).update(
                status=Status.FAILED, error_stage=runner.stage or "", error_code=error["error_code"],
                error_message=error["error"], retryable=error["retryable"],
                status_detail=_failed_detail(runner.stage), updated_at=timezone.now(),
            )
        return False


class IngestionRunner:
    def __init__(self, job):
        self.job = job
        self.document = job.document
        self.stage = None
        self.engine = None

    # Every write goes through here: it is the heartbeat and the ownership check.
    def _advance(self, status, progress, detail, **document_fields):
        self.stage = status
        self._write(progress, detail, status=status, **document_fields)

    def _write(self, progress, detail, status=None, **document_fields):
        now = timezone.now()
        owned = Job.objects.filter(pk=self.job.pk, status=Job.Status.PROCESSING).update(progress=progress, updated_at=now)
        if not owned:
            raise IngestionAborted()
        values = {"progress": progress, "status_detail": detail[:255], "updated_at": now, **document_fields}
        if status is not None:
            values["status"] = status
        Document.objects.filter(pk=self.document.pk).update(**values)

    def _merge_metadata(self, updates):
        metadata = {**(self.document.metadata or {}), **updates}
        self.document.metadata = metadata
        return metadata

    def run(self):
        document = self.document
        kept = self._legacy_text_to_keep(document)
        if kept is not None:
            text, pages = kept, None
            self._advance(Status.EXTRACTING, 5, "Using the text saved when this document was added")
            self._advance(Status.CLEANING, 15, "Keeping the saved text so existing ground truth stays valid")
            metadata = self._merge_metadata({
                "text_source": "legacy", "page_count": None, "pages": None,
                "char_count": len(text), "word_count": extraction.count_words(text),
            })
            self._write(20, "Content kept", metadata=metadata)
        else:
            text, pages = self._extract_and_clean(document)

        self._advance(Status.CHUNKING, 20, "Splitting text into chunks")
        self.engine = engine = chat_engine()
        # The same chunker `_build_index` will use, so the texts embedded
        # below are exactly the texts the index needs.
        chunks = engine.chunker.chunk(text)
        if not chunks:
            raise extraction.no_text_error()
        metadata = self._merge_metadata({"chunk_count": len(chunks)})
        self._write(25, f"Created {len(chunks):,} chunks", metadata=metadata)

        dense = dense_engine_of(engine)
        self._embed(EmbeddingCache(document.pk, dense.model), dense, chunks)

        self._advance(Status.INDEXING, EMBEDDING_END, "Building the search index")
        document.refresh_from_db()
        with engine_execution(engine):
            location = engine._build_index(document.user.username, document)
        vector = (
            DocumentVector.objects.filter(document=document, vectorstore_location=location)
            .order_by("-created_at").first()
            or DocumentVector.objects.filter(document=document, status="ready", method="dense")
            .order_by("-created_at", "-id").first()
        )
        self._write(95, "Recording passage positions", current_index=vector)
        self._record_positions(engine, text, chunks, pages)

        metadata = self._merge_metadata({
            "embedding_model": dense.model,
            "chunk_config": engine._get_chunk_config(),
        })
        now = timezone.now()
        finished = Job.objects.filter(pk=self.job.pk, status=Job.Status.PROCESSING).update(
            status=Job.Status.READY, progress=100, error_message="", error_code="", retryable=False, updated_at=now,
        )
        if not finished:
            raise IngestionAborted()
        self.stage = Status.READY
        Document.objects.filter(pk=document.pk).update(
            status=Status.READY, progress=100, status_detail="Ready", metadata=metadata,
            current_index=vector, ingested_at=now, error_stage="", error_code="", error_message="",
            retryable=False, updated_at=now,
        )

    def _extract_and_clean(self, document):
        """EXTRACTING and CLEANING. Returns (text, pages or None)."""
        self._advance(Status.EXTRACTING, 5, "Fetching the page" if document.source_type == "url" else "Extracting text")
        extracted = extraction.extract_document(document)
        fields = dict(extracted.document_updates)
        metadata = self._merge_metadata(extracted.metadata_updates)
        if extracted.title and metadata.get("auto_title"):
            fields["name"] = extracted.title[:255]
            metadata = self._merge_metadata({"auto_title": False})
        for key, value in fields.items():
            setattr(document, key, value)
        self._write(15, "Text extracted", metadata=metadata, **fields)

        self._advance(Status.CLEANING, 15, "Cleaning extracted text")
        clean = extraction.clean_pages(extracted)
        if not clean.text.strip():
            raise extraction.no_text_error()
        text_path = default_storage.save(
            f"{extraction_directory(document)}/extracted.txt", ContentFile(clean.text.encode("utf-8")),
        )
        old_text_path = document.extracted_text_path
        document.extracted_text_path = text_path
        # Page fields stay null for sources without real pages (PRD §14).
        pages = clean.pages if extracted.paged else None
        metadata = self._merge_metadata({
            "text_source": "extracted",
            "page_count": extracted.page_count if extracted.paged else None,
            "pages": pages,
            "char_count": len(clean.text),
            "word_count": extraction.count_words(clean.text),
        })
        self._write(20, "Content cleaned", extracted_text_path=text_path, metadata=metadata)
        if old_text_path and old_text_path not in (text_path, document.source_path):
            # Re-extraction wrote a fresh copy; the old one is now unreferenced
            # and would otherwise pile up with every re-index.
            delete_storage_path(old_text_path)
        return clean.text, pages

    def _legacy_text_to_keep(self, document):
        """The legacy extracted text to index verbatim, or None to re-extract.

        This pipeline extracts differently from the legacy loader (pages are
        separated by blank lines, web pages are read as articles), so
        re-extracting a legacy document changes every chunk, and
        `_sync_chunks` then deletes the old chunks — together with the
        deep-analysis ground truth attached to them. When such ground truth
        exists, the text it was labelled against is kept instead (without page
        numbers, which the legacy text never had).
        """
        if (document.metadata or {}).get("text_source") == "extracted" or not document.extracted_text_path:
            return None
        if not GroundTruthChunk.objects.filter(chunk__document=document).exists():
            return None
        try:
            # Exactly what _build_index will read and chunk.
            text = DataLoader().load(document.extracted_text_path)
        except Exception:
            logger.warning("Legacy text of document %s is unreadable; re-extracting", document.pk, exc_info=True)
            return None
        return text if text.strip() else None

    def _embed(self, cache, dense, chunks):
        unique = list(dict.fromkeys(chunks))
        missing = cache.missing(unique)
        done = len(unique) - len(missing)
        total = len(unique)
        self._advance(Status.EMBEDDING, _embedding_progress(done, total), _embedded_detail(done, total))
        for start in range(0, len(missing), EMBEDDING_BATCH_SIZE):
            batch = missing[start:start + EMBEDDING_BATCH_SIZE]
            vectors = embed_texts(dense.client, batch, dense.model)
            # Committed before the next provider call: this is the checkpoint.
            cache.store(batch, vectors)
            done += len(batch)
            self._write(_embedding_progress(done, total), _embedded_detail(done, total))

    def _record_positions(self, engine, text, chunks, pages):
        positions = chunk_positions(text, chunks, pages)
        first_position = {}
        for chunk_text, position in zip(chunks, positions):
            first_position.setdefault(chunk_text, position)
        rows = list(Chunk.objects.filter(document=self.document, config_hash=engine._get_config_hash()))
        changed = []
        for row in rows:
            position = first_position.get(row.text)
            if position is None:
                continue
            # Merged, not replaced: the chunk config recorded by _sync_chunks stays.
            row.metadata = {**(row.metadata or {}), **position}
            changed.append(row)
        if changed:
            Chunk.objects.bulk_update(changed, ["metadata"], batch_size=500)


def _embedding_progress(done, total):
    if not total:
        return EMBEDDING_END
    return EMBEDDING_START + int((EMBEDDING_END - EMBEDDING_START) * done / total)


def _embedded_detail(done, total):
    return f"Embedded {done:,} of {total:,} chunks"


def extraction_directory(document):
    """Where derived files for `document` live: next to its original if it has
    one in the standard layout, else a fresh per-document directory."""
    directory = directory_of(document.source_path)
    if directory and directory.startswith(f"documents/user_{document.user_id}/"):
        return directory
    directory = directory_of(document.extracted_text_path)
    if directory and directory.startswith(f"documents/user_{document.user_id}/"):
        return directory
    return document_directory(document.user)

