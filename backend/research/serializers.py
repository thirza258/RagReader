"""JSON shape of a research task (docs/prd-implementation.md, Phase 5)."""
from research.models import ResearchTask
from router.models import Document


def task_payload(task, *, full=True):
    titles = dict(Document.objects.filter(pk__in=task.document_ids or []).values_list("pk", "name"))
    pipeline = task.pipeline or {}
    error = None
    if task.error_code:
        error = {"code": task.error_code, "message": task.error_message, "retryable": task.retryable,
                 "stage": task.error_stage or None}
    payload = {
        "id": task.pk, "workspace_id": task.workspace_id, "kind": task.kind,
        "kind_label": ResearchTask.Kind(task.kind).label, "title": task.title, "status": task.status,
        "input": task.input or {},
        "documents": [{"id": pk, "title": titles.get(pk)} for pk in task.document_ids or []],
        "pipeline": {"id": pipeline.get("pipeline_id"), "name": pipeline.get("name"),
                     "version_id": pipeline.get("version_id"), "version": pipeline.get("version"),
                     "strategy": (pipeline.get("config") or {}).get("strategy"),
                     "available": task.pipeline_version_id is not None},
        "progress": task.progress or {}, "error": error, "run_id": task.run_id, "latency_ms": task.latency_ms,
        "notes": task.notes, "created_at": task.created_at, "updated_at": task.updated_at,
        "started_at": task.started_at, "finished_at": task.finished_at,
    }
    if full:
        payload["result"] = task.result
        payload["evidence"] = task.evidence or []
    return payload
