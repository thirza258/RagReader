"""Eligibility for the optional stages on follow-up analysis runs."""
from common.constant import build_variants, normalize_analysis_config
from common.errors import PipelineError
from datetime import timedelta
from contextlib import contextmanager
from threading import Event, Thread
from django.db import close_old_connections, transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from router.models import AnalysisBatch, AnalysisResult


def has_completed_analysis(conversation_id):
    if not conversation_id:
        return False
    batches = AnalysisBatch.objects.filter(conversation_id=conversation_id).only("id", "config").prefetch_related(
        Prefetch("results", queryset=AnalysisResult.objects.only("batch_id", "method", "ai_model", "error_message")),
    )
    for batch in batches:
        expected = {(v["method"], v["model"]) for v in build_variants(batch.config)}
        completed = {(r.method, r.ai_model) for r in batch.results.all() if not r.error_message}
        if expected.issubset(completed):
            return True
    return False


LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 20


def claim_batch(batch_id, token):
    now = timezone.now()
    return bool(AnalysisBatch.objects.filter(pk=batch_id).filter(
        Q(execution_token__isnull=True) | Q(execution_updated_at__isnull=True) | Q(execution_updated_at__lt=now - timedelta(seconds=LEASE_SECONDS)),
    ).update(execution_token=token, execution_updated_at=now))


def renew_batch(batch_id, token):
    return bool(AnalysisBatch.objects.filter(pk=batch_id, execution_token=token).update(execution_updated_at=timezone.now()))


def release_batch(batch_id, token):
    AnalysisBatch.objects.filter(pk=batch_id, execution_token=token).update(execution_token=None, execution_updated_at=None)


@contextmanager
def keep_batch_lease(batch_id, token):
    """Keep a Celery execution claim alive independently of blocking API calls."""
    stopped = Event()
    def heartbeat():
        while not stopped.wait(HEARTBEAT_SECONDS):
            close_old_connections()
            try:
                if not renew_batch(batch_id, token):
                    break
            except Exception:
                # Ownership is checked before saving; a lost lease never writes.
                pass
            finally:
                close_old_connections()
    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1)
        release_batch(batch_id, token)


def format_metrics(metrics):
    if isinstance(metrics, dict):
        return metrics
    result = {}
    for metric in metrics or []:
        if isinstance(metric, dict) and "name" in metric and "value" in metric:
            result[metric["name"]] = metric["value"]
        elif isinstance(metric, dict):
            result.update(metric)
    return result


def result_frame(batch, result):
    frame = {"batch_id": str(batch.job_id), "method": result.method,
             "aiModel": result.ai_model, "query": result.query, "progress": 100}
    if result.error_message:
        return {**frame, "error": result.error_message, "error_code": result.error_code, "retryable": result.retryable}
    chunks = [{"id": doc.get("id", doc.get("chunk_id")), "chunk_id": doc.get("id", doc.get("chunk_id")),
               "text": doc.get("text", ""), "score": doc.get("score")} for doc in result.retrieved_chunks or []]
    return {**frame, "answer": result.answer, "context": chunks, "retrievedChunks": chunks,
            "evaluation": format_metrics(result.evaluation_metrics)}


def batch_snapshot(batch):
    config = normalize_analysis_config(batch.config)
    expected = {(variant["method"], variant["model"]) for variant in build_variants(config)}
    results = [result for result in batch.results.all() if (result.method, result.ai_model) in expected]
    completed = sum(not result.error_message for result in results)
    failed = sum(bool(result.error_message) for result in results)
    total = len(expected)
    finished = completed + failed
    return {"batch_id": str(batch.job_id), "config": config, "total": total,
            "completed": completed, "failed": failed, "finished": finished,
            "progress": min(100, int(finished / total * 100)) if total else 0,
            "is_complete": bool(total and completed == total),
            "is_finished": bool(total and finished == total),
            "results": [result_frame(batch, result) for result in results]}


def completion_frame(snapshot):
    outcome = "completed" if snapshot["is_complete"] else "partial_failure" if snapshot["completed"] else "failed"
    return {"status": "COMPLETE", "batch_id": snapshot["batch_id"], "progress": 100,
            "outcome": outcome, "completed": snapshot["completed"], "failed": snapshot["failed"], "total": snapshot["total"]}


@transaction.atomic
def save_variant(batch, method, model, response=None, error=None, *, token=None):
    if token is not None:
        # Check ownership and save under the same row lock, preventing an old
        # worker from overwriting a result after another worker takes over.
        owned = AnalysisBatch.objects.select_for_update().get(pk=batch.pk)
        if owned.execution_token != token:
            raise PipelineError("analysis_lease_lost", "This analysis was resumed by another worker. Reconnect to follow the same batch.", retryable=True, http_status=409)
    if error:
        values = {"answer": "", "retrieved_chunks": [], "evaluation_metrics": [],
                  "error_message": error["error"], "error_code": error["error_code"], "retryable": error["retryable"]}
    else:
        answer = response.get("answer") if isinstance(response, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            raise PipelineError("empty_model_response", "The answer model returned an empty response. Try again.", retryable=True, http_status=502)
        context = response.get("context", [])
        metrics = {**response.get("evaluation", {}), "retrieval_score": [
            {"chunk_id": doc.get("chunk_id", doc.get("id")), "score": doc.get("score")} for doc in context]}
        if response.get("module_trace"):
            metrics["module_trace"] = response["module_trace"]
        chunks = [{"id": doc.get("chunk_id", doc.get("id")), "text": doc.get("text", ""), "score": doc.get("score")} for doc in context]
        values = {"answer": answer, "retrieved_chunks": chunks,
                  "evaluation_metrics": [{"name": key, "value": value} for key, value in metrics.items()],
                  "error_message": "", "error_code": "", "retryable": False}
    result, _ = AnalysisResult.objects.update_or_create(batch=batch, method=method, ai_model=model, defaults={"query": batch.query, **values})
    return result
