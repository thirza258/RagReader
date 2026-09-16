import logging
from uuid import UUID, uuid4

from celery import shared_task
from celery.exceptions import Retry
from django.utils import timezone

from .models import Job, AnalysisBatch, AnalysisResult
from rag.rag_service import apply_retrieval_depth, engine_execution, rag_registry
from common.constant import normalize_analysis_config
from common.errors import PipelineError, error_payload
from router.analysis import claim_batch, keep_batch_lease, renew_batch, save_variant

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=1800, time_limit=1860)
def initialize_rag_task(self, job_id, username, method, model_config):
    job = None
    try:
        job = Job.objects.select_related("user", "document").get(pk=UUID(str(job_id)))
        if job.status == Job.Status.READY:
            return True
        # A duplicate delivery must not start a second embedding operation.
        claimed = Job.objects.filter(pk=job.pk, status=Job.Status.PENDING).update(
            status=Job.Status.PROCESSING, progress=10, updated_at=timezone.now(),
        )
        if not claimed:
            return False
        job.refresh_from_db()
        if not job.document:
            raise PipelineError("missing_document", "The initialization job has no document. Upload a document and try again.", http_status=400)
        engine = rag_registry.get_engine(method, model_config)
        with engine_execution(engine):
            if engine.init_job(job.user.username, job=job) is False:
                raise PipelineError("initialization_failed", "The retrieval index could not be initialized. Try again.", retryable=True)
        return bool(Job.objects.filter(pk=job.pk, status=Job.Status.PROCESSING).update(
            status=Job.Status.READY, progress=100, error_message="", error_code="", retryable=False,
            updated_at=timezone.now(),
        ))
    except Exception as exc:
        logger.warning("Initialization failed for job %s", job_id, exc_info=True)
        if job is not None:
            error = error_payload(exc, code="initialization_failed", message="Document initialization failed. Try initializing this document again.")
            job.mark_failed(error["error"], error["error_code"], error["retryable"])
        return False


@shared_task(bind=True)
def run_single_analysis(self, batch_id, username, query, variant_config, config=None):
    """Queued execution uses the same IDs, lease and durable errors as streaming."""
    batch, token, owned = None, uuid4(), False
    method, model = variant_config["method"], variant_config["model"]
    try:
        batch = AnalysisBatch.objects.select_related("user", "conversation").get(job_id=UUID(str(batch_id)))
        existing = AnalysisResult.objects.filter(batch=batch, method=method, ai_model=model).first()
        if existing:
            return not bool(existing.error_message)
        owned = claim_batch(batch.pk, token)
        if not owned:
            raise self.retry(countdown=5, max_retries=240)
        with keep_batch_lease(batch.pk, token):
            try:
                # Another owner may have saved just before this claim.
                existing = AnalysisResult.objects.filter(batch=batch, method=method, ai_model=model).first()
                if existing:
                    return not bool(existing.error_message)
                normalized = normalize_analysis_config(batch.config or config)
                engine = rag_registry.get_engine(method, model, normalized)
                with engine_execution(engine):
                    apply_retrieval_depth(engine, normalized["top_k"], normalized["child_top_k"])
                    if batch.conversation and batch.conversation.document_id:
                        response = engine.run_analysis(batch.conversation.document_id, batch.conversation_id)
                    elif normalized["modules"]:
                        raise PipelineError("missing_document", "Module analysis requires a conversation document.", http_status=400)
                    else:
                        # Historical queued batches may predate conversations.
                        response = engine.run(batch.user.username, batch.query)
                if not renew_batch(batch.pk, token):
                    return False
                save_variant(batch, method, model, response=response, token=token)
                return True
            except Exception as exc:
                if renew_batch(batch.pk, token):
                    save_variant(batch, method, model, error=error_payload(exc), token=token)
                logger.warning("Queued analysis variant failed for %s", batch_id, exc_info=True)
                return False
    except Retry:
        raise
    except Exception:
        logger.warning("Could not run queued analysis %s", batch_id, exc_info=True)
        return False
