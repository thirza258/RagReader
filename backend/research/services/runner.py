"""Research task lifecycle: validate, queue, run, cancel, retry, export (PRD §47).

    queued → running → completed | failed | cancelled      (retry re-queues)

A worker claims a queued task by its `run_token`; progress updates double as
heartbeats and ownership checks, and the result and run record are written
in one transaction that re-checks ownership, so a cancelled, retried or
deleted task is never overwritten by a worker that lost it.
"""
import logging
import re
import time
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from common.errors import PipelineError
from lab.services.runner import corpus_documents_from_ids
from research.models import ResearchTask
from research.services import engine
from router.models import Document
from workspace.errors import ApiError, describe_exception
from workspace.models import PipelineVersion, RetrievalRun
from workspace.services import llms, pipelines, tracing
from workspace.services import runs as run_store
from workspace.services.ingestion import chat_engine
from workspace.services.retrieval import retrieval_parameters

logger = logging.getLogger(__name__)

Status = ResearchTask.Status
Kind = ResearchTask.Kind
INVALID = "The request contains invalid or missing fields."
STALL_AFTER = timedelta(minutes=15)
QUEUE_FAILURE_MESSAGE = "The research worker could not be reached. Retry the task shortly."
LIMITS = {
    "claim": 1000, "question": 2000, "topic": 500, "title": 200, "notes": 10000,
    "dimension": 80, "dimensions": 10, "field_name": 60, "field_description": 300, "fields": 20,
    "compare_documents": (2, 4),
}
FIELD_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_ ]{0,59}$")


class LostOwnership(Exception):
    """The task was cancelled, retried or deleted while this worker ran."""


def invalid(details):
    return ApiError("invalid_request", INVALID, details=details)


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _text(data, key, limit, errors, *, required):
    value = data.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors[key] = ["This field is required."]
        return None
    if not isinstance(value, str):
        errors[key] = ["Expected text."]
        return None
    value = " ".join(value.split()) if key != "notes" else value.strip()
    if len(value) > limit:
        errors[key] = [f"Keep it under {limit} characters."]
        return None
    return value


# ── Input ────────────────────────────────────────────────────────────────────

def clean_input(kind, data, errors):
    """The kind-specific input, normalised; problems go into `errors`."""
    if kind == Kind.VERIFY_CLAIM:
        return {"claim": _text(data, "claim", LIMITS["claim"], errors, required=True)}
    if kind in (Kind.ASK, Kind.REPORT):
        return {"question": _text(data, "question", LIMITS["question"], errors, required=True)}
    if kind == Kind.CONTRADICTIONS:
        return {"topic": _text(data, "topic", LIMITS["topic"], errors, required=True)}
    if kind == Kind.COMPARE:
        raw = data.get("dimensions")
        if raw in (None, []):
            return {"dimensions": list(engine.DEFAULT_DIMENSIONS)}
        if not isinstance(raw, list) or len(raw) > LIMITS["dimensions"]:
            errors["dimensions"] = [f"Give up to {LIMITS['dimensions']} dimensions."]
            return {"dimensions": []}
        dimensions = []
        for value in raw:
            name = " ".join(value.split()) if isinstance(value, str) else ""
            if not name or len(name) > LIMITS["dimension"]:
                errors["dimensions"] = [f"Each dimension is 1–{LIMITS['dimension']} characters of text."]
                break
            if name.lower() not in [entry.lower() for entry in dimensions]:
                dimensions.append(name)
        return {"dimensions": dimensions}
    if kind == Kind.EXTRACT:
        raw = data.get("fields")
        if not isinstance(raw, list) or not 1 <= len(raw) <= LIMITS["fields"]:
            errors["fields"] = [f"Give 1–{LIMITS['fields']} fields to extract."]
            return {"fields": []}
        fields, names = [], set()
        for position, entry in enumerate(raw):
            entry = {"name": entry} if isinstance(entry, str) else entry
            if not isinstance(entry, dict):
                errors[f"fields[{position}]"] = ["Expected a field name or {name, type, description}."]
                continue
            name = " ".join(str(entry.get("name") or "").split()).replace(" ", "_")
            kind_value = entry.get("type") or "text"
            description = entry.get("description") or ""
            problems = []
            if not FIELD_NAME.match(name):
                problems.append("Use a name of letters, digits and underscores (max 60), starting with a letter.")
            elif name.lower() in names:
                problems.append(f"“{name}” is listed twice.")
            if kind_value not in engine.FIELD_TYPES:
                problems.append(f"Type must be one of {', '.join(engine.FIELD_TYPES)}.")
            if not isinstance(description, str) or len(description) > LIMITS["field_description"]:
                problems.append(f"The description is text of at most {LIMITS['field_description']} characters.")
            if problems:
                errors[f"fields[{position}]"] = problems
                continue
            names.add(name.lower())
            fields.append({"name": name, "type": kind_value, "description": " ".join(description.split())})
        return {"fields": fields}
    errors["kind"] = [f"Choose one of {', '.join(Kind.values)}."]
    return {}


def resolve_pipeline_version(workspace, data, errors):
    version_id, pipeline_id = data.get("pipeline_version_id"), data.get("pipeline_id")
    if version_id not in (None, ""):
        pk = _int(version_id)
        version = (PipelineVersion.objects.select_related("pipeline")
                   .filter(pk=pk, pipeline__workspace=workspace).first() if pk else None)
        if version is None:
            errors["pipeline_version_id"] = [f"Pipeline version {version_id} is not in this workspace."]
        return version
    if pipeline_id not in (None, ""):
        return pipelines.latest_version(pipelines.pipeline_in_workspace(workspace, _int(pipeline_id)))
    return pipelines.latest_version(pipelines.default_pipeline_for(workspace))


def default_title(kind, data):
    first = data.get("claim") or data.get("question") or data.get("topic")
    if first:
        return first[:LIMITS["title"]]
    if kind == Kind.COMPARE:
        return "Compare documents"
    if kind == Kind.EXTRACT:
        return "Extract " + ", ".join(field["name"] for field in data.get("fields", []))[:180]
    return Kind(kind).label


def create_task(user, workspace, data):
    if not isinstance(data, dict):
        raise invalid({"body": ["Expected a JSON object."]})
    errors = {}
    kind = data.get("kind")
    if kind not in Kind.values:
        raise invalid({"kind": [f"Choose one of {', '.join(Kind.values)}."]})
    task_input = clean_input(kind, data, errors)
    title = _text(data, "title", LIMITS["title"], errors, required=False)
    raw_ids = data.get("document_ids")
    if raw_ids is not None and (not isinstance(raw_ids, list) or any(_int(value) is None for value in raw_ids)):
        errors["document_ids"] = ["Expected a list of document ids."]
        raw_ids = None
    version = resolve_pipeline_version(workspace, data, errors)
    if errors:
        raise invalid(errors)
    ids = list(dict.fromkeys(_int(value) for value in raw_ids or []))
    documents = corpus_documents_from_ids(workspace, ids)
    low, high = LIMITS["compare_documents"]
    if kind == Kind.COMPARE and not low <= len(documents) <= high:
        raise invalid({"document_ids": [f"Choose {low}–{high} READY documents to compare."]})
    pipelines.check_documents(version, documents)
    with transaction.atomic():
        task = ResearchTask.objects.create(
            workspace=workspace, kind=kind, title=title or default_title(kind, task_input), input=task_input,
            document_ids=[document.pk for document in documents], pipeline_version=version,
            pipeline=pipelines.snapshot(version),
        )
        _queue(task)
    task.refresh_from_db()
    return task


def _queue(task):
    """Queue with a new token after commit; on an unreachable worker the task fails retryably."""
    token = uuid.uuid4()
    now = timezone.now()
    ResearchTask.objects.filter(pk=task.pk).update(
        status=Status.QUEUED, run_token=token, heartbeat_at=now, updated_at=now, progress={},
        error_code="", error_message="", error_stage="", retryable=False, finished_at=None,
    )

    def enqueue():
        from research import tasks
        try:
            tasks.run_research_task.delay(task.pk, str(token))
        except Exception:
            logger.warning("Could not enqueue research task %s", task.pk, exc_info=True)
            ResearchTask.objects.filter(pk=task.pk, run_token=token).update(
                status=Status.FAILED, run_token=None, error_code="job_queue_unavailable",
                error_message=QUEUE_FAILURE_MESSAGE, retryable=True, updated_at=timezone.now(),
            )

    transaction.on_commit(enqueue)


def retry_task(task):
    expire_if_stalled(task)
    if task.status not in (Status.FAILED, Status.CANCELLED):
        raise ApiError("task_not_retryable", "Only a failed or cancelled task can be retried.", status=409)
    with transaction.atomic():
        _queue(task)
    task.refresh_from_db()
    return task


def cancel_task(task):
    updated = ResearchTask.objects.filter(pk=task.pk, status__in=(Status.QUEUED, Status.RUNNING)).update(
        status=Status.CANCELLED, run_token=None, finished_at=timezone.now(), updated_at=timezone.now(),
    )
    if not updated:
        raise ApiError("task_not_running", "Only a queued or running task can be cancelled.", status=409)
    task.refresh_from_db()
    return task


def delete_task(task):
    with transaction.atomic():
        run_id = task.run_id
        task.delete()
        if run_id:
            RetrievalRun.objects.filter(pk=run_id, source=RetrievalRun.Source.RESEARCH).delete()


def expire_if_stalled(task):
    if task.status not in (Status.QUEUED, Status.RUNNING):
        return task
    last = task.heartbeat_at or task.updated_at
    if last and last < timezone.now() - STALL_AFTER:
        ResearchTask.objects.filter(pk=task.pk, status=task.status, run_token=task.run_token).update(
            status=Status.FAILED, run_token=None, error_code="task_stalled", retryable=True,
            error_message="The task stopped making progress. Retry it.", updated_at=timezone.now(),
        )
        task.refresh_from_db()
    return task


# ── The worker ───────────────────────────────────────────────────────────────

def _ms(since):
    return int(round((time.monotonic() - since) * 1000))


def primary_text(task):
    data = task.input or {}
    return data.get("claim") or data.get("question") or data.get("topic") or task.title


def _provenance(task, session, config, model):
    return {
        "schema_version": 1, "timestamp": session.tracer.started_at.isoformat(),
        "strategy": config.get("strategy"), "retrieval_parameters": retrieval_parameters(config),
        "embedding_model": config.get("embedding_model"), "reranker": None,
        "generation_model": model, "configured_generation_model": config.get("generation_model"),
        "fallback_used": False, "generation_parameters": {"temperature": 0.0, "stream": False},
        "prompt_version": engine.PROMPT_VERSION, "index_versions": session.indexes[:run_store.MAX_RUN_INDEX_VERSIONS],
        "index_version_count": len(session.documents), "pipeline": task.pipeline,
        "research": {"task_id": task.pk, "kind": task.kind},
    }


def _record_run(task, session, config, *, status, error=None, stage=""):
    try:
        cited = sum(1 for item in session.book.items if item.get("cited"))
        with transaction.atomic():
            return run_store.save_run(
                user=task.workspace.user, workspace=task.workspace, source=RetrievalRun.Source.RESEARCH, status=status,
                query_original=primary_text(task), error=error, error_stage=stage,
                provenance=_provenance(task, session, config, config.get("generation_model")),
                latency={"total": session.tracer.elapsed_ms() and int(session.tracer.elapsed_ms()),
                         "retrieval": session.retrieval_ms, "generation": session.generation_ms},
                counts={"candidates": len(session.book.items), "context": len(session.book.items), "cited": cited},
                started_at=session.tracer.started_at, spans=session.tracer.export(), candidates=session.book.rows,
                pipeline_version=task.pipeline_version,
            )
    except Exception:
        logger.warning("Could not record the research run for task %s", task.pk, exc_info=True)
        return None


def run_task(task_id, token):
    """Body of research.tasks.run_research_task. True when the task completed."""
    try:
        token = uuid.UUID(str(token))
    except (TypeError, ValueError):
        return False
    began = time.monotonic()
    now = timezone.now()
    if not ResearchTask.objects.filter(pk=task_id, status=Status.QUEUED, run_token=token).update(
            status=Status.RUNNING, started_at=now, heartbeat_at=now, updated_at=now):
        return False
    task = ResearchTask.objects.select_related("workspace", "workspace__user", "pipeline_version__pipeline").get(pk=task_id)
    config = (task.pipeline or {}).get("config") or {}
    tracer = tracing.new_tracer("research.task", Kind(task.kind).label, origin=began)

    def on_progress(stage, detail):
        moment = timezone.now()
        if not ResearchTask.objects.filter(pk=task_id, status=Status.RUNNING, run_token=token).update(
                progress={"stage": stage, "detail": detail[:200]}, heartbeat_at=moment, updated_at=moment):
            raise LostOwnership()

    session = None
    stage = "prepare"
    try:
        documents = list(Document.objects.filter(pk__in=task.document_ids, workspace=task.workspace,
                                                 user=task.workspace.user, status=Document.Status.READY))
        documents.sort(key=lambda document: task.document_ids.index(document.pk))
        if not documents:
            raise PipelineError("no_ready_documents", "None of the task's documents is READY any more.", http_status=409)
        if task.pipeline_version is not None:
            pipelines.check_documents(task.pipeline_version, documents)
        chat = chat_engine()
        session = engine.Session(documents=documents, config=config, engine=chat,
                                 llm=llms.generation_llm(chat, config.get("generation_model")), tracer=tracer,
                                 on_progress=on_progress)
        stage = "analyze"
        result, evidence = engine.execute(session, task.kind, task.input)
        tracer.close()
        with transaction.atomic():
            if not ResearchTask.objects.filter(pk=task_id, status=Status.RUNNING, run_token=token).exists():
                raise LostOwnership()
            run = _record_run(task, session, config, status=RetrievalRun.Status.COMPLETED)
            ResearchTask.objects.filter(pk=task_id).update(
                status=Status.COMPLETED, run_token=None, result=result, evidence=evidence, run=run,
                progress={}, latency_ms=_ms(began), finished_at=timezone.now(), updated_at=timezone.now(),
            )
        return True
    except LostOwnership:
        return False
    except Exception as exc:
        _status, error = describe_exception(exc)
        if not isinstance(exc, (ApiError, PipelineError)):
            logger.warning("Research task %s failed", task_id, exc_info=True)
        tracer.close(error=error["code"])
        run = _record_run(task, session, config, status=RetrievalRun.Status.FAILED, error=error, stage=stage) \
            if session is not None else None
        ResearchTask.objects.filter(pk=task_id, status=Status.RUNNING, run_token=token).update(
            status=Status.FAILED, run_token=None, error_code=error["code"][:80], error_message=error["message"],
            error_stage=stage, retryable=bool(error.get("retryable")), run=run, progress={},
            latency_ms=_ms(began), finished_at=timezone.now(), updated_at=timezone.now(),
        )
        return False


def fail_timeout(task_id, token):
    ResearchTask.objects.filter(pk=task_id, run_token=uuid.UUID(str(token)),
                                status__in=(Status.QUEUED, Status.RUNNING)).update(
        status=Status.FAILED, run_token=None, error_code="task_timeout", retryable=True,
        error_message="The task ran past the worker's time limit. Retry it.", finished_at=timezone.now(),
        updated_at=timezone.now(),
    )


# ── Markdown export ──────────────────────────────────────────────────────────

def _references(evidence):
    lines = []
    for item in evidence:
        if not item.get("cited"):
            continue
        where = item.get("document_title") or f"Document {item.get('document_id')}"
        if item.get("page_number"):
            where += f", p. {item['page_number']}"
        snippet = " ".join((item.get("text") or "").split())[:240]
        lines.append(f"[{item['citation_id']}] {where} — “{snippet}”")
    return lines


def to_markdown(task):
    result, lines = task.result or {}, [f"# {task.title}", ""]
    lines.append(f"*{Kind(task.kind).label} · {task.status} · pipeline {task.pipeline.get('name', '?')} "
                 f"v{task.pipeline.get('version', '?')}*")
    lines.append("")
    if task.status != Status.COMPLETED:
        lines += [f"This task has not completed ({task.error_message or task.status}).", ""]
    elif task.kind == Kind.VERIFY_CLAIM:
        lines += [f"**Claim:** {result.get('claim')}", "",
                  f"**Verdict:** {result.get('verdict', '').replace('_', ' ')} ({result.get('confidence')} confidence)",
                  "", f"- Supporting passages: {', '.join(f'[{n}]' for n in result.get('supporting', [])) or 'none'}",
                  f"- Contradicting passages: {', '.join(f'[{n}]' for n in result.get('contradicting', [])) or 'none'}",
                  "", result.get("conclusion") or "", ""]
    elif task.kind == Kind.ASK:
        lines += [f"**Question:** {result.get('question')}", ""]
        for row in result.get("per_document", []):
            lines += [f"## {row.get('document_title')}", "", row.get("answer") or "*Not addressed in this document.*", ""]
        lines += ["## Comparison", "", result.get("comparison") or "—", "", "## Synthesis", "",
                  result.get("synthesis") or "—", ""]
    elif task.kind == Kind.COMPARE:
        documents = result.get("documents", [])
        lines += ["| Dimension | " + " | ".join(doc["title"] for doc in documents) + " | Difference |",
                  "| --- | " + " | ".join("---" for _ in documents) + " | --- |"]
        for row in result.get("dimensions", []):
            cells = [(cell.get("finding") or "not stated").replace("|", "\\|") for cell in row.get("findings", [])]
            lines.append(f"| {row['name']} | " + " | ".join(cells) + f" | {(row.get('difference') or '—').replace('|', '\\|')} |")
        lines += ["", result.get("summary") or "", ""]
    elif task.kind == Kind.EXTRACT:
        lines += ["| Field | Value | Sources |", "| --- | --- | --- |"]
        for row in result.get("fields", []):
            value = row.get("value")
            shown = "; ".join(value) if isinstance(value, list) else ("—" if value is None else str(value))
            sources = ", ".join(f"[{n}]" for n in row.get("citation_ids", [])) or row.get("status", "")
            lines.append(f"| {row['name']} | {shown.replace('|', '\\|')} | {sources} |")
        lines.append("")
    elif task.kind == Kind.CONTRADICTIONS:
        lines += [f"**Topic:** {result.get('topic')}", ""]
        for pair in result.get("contradictions", []) or []:
            lines.append(f"- [{pair['a']}] vs [{pair['b']}] ({pair['severity']}): {pair.get('explanation') or ''}")
        if not result.get("contradictions"):
            lines.append("No contradictions were found.")
        lines += ["", result.get("summary") or "", ""]
    elif task.kind == Kind.REPORT:
        lines += [f"**Question:** {result.get('question')}", "", "## Summary", "", result.get("summary") or "", ""]
        for section in result.get("sections", []):
            lines += [f"## {section['heading']}", "", section.get("body") or "", ""]
        if result.get("limitations"):
            lines += ["## Limitations", "", result["limitations"], ""]
    references = _references(task.evidence or [])
    if references:
        lines += ["## References", ""] + references + [""]
    return "\n".join(lines).rstrip() + "\n"
