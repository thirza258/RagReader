"""Request validation and the JSON shapes of docs/prd-implementation.md.

Responses are built by plain functions rather than ModelSerializers: the
shapes are a cross-team contract, and spelling every key out makes a drift
from it visible in review.
"""
from rest_framework import serializers

from router.models import Document, Job
from workspace.models import ChatMessage, RetrievalRun
from workspace.services.tracing import build_tree
from workspace.views.base import MAX_ID
MAX_SCOPE_DOCUMENTS = 200
RUN_LIST_DEFAULT_LIMIT = 50
RUN_LIST_MAX_LIMIT = 200
SUMMARY_DEFAULT_DAYS = 30
SUMMARY_MAX_DAYS = 365
MAX_QUESTION_CHARS = 4000
PREVIEW_CHARS = 140

FILE_SOURCE_TYPES = {"pdf", "docx", "txt", "md", "markdown"}
TERMINAL_STATUSES = {Document.Status.READY, Document.Status.FAILED}

# Used when a legacy row never recorded its MIME type.
MIME_BY_SOURCE_TYPE = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "text": "text/plain",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "url": "text/html",
}

# The checklist the frontend renders, in order (PRD §9).
INGESTION_STAGES = [
    (Document.Status.UPLOADING, "Uploaded"),
    (Document.Status.EXTRACTING, "Text extracted"),
    (Document.Status.CLEANING, "Content cleaned"),
    (Document.Status.CHUNKING, "Chunks created"),
    (Document.Status.EMBEDDING, "Embeddings generated"),
    (Document.Status.INDEXING, "Index built"),
]
STAGE_IDS = [stage for stage, _label in INGESTION_STAGES]


# ── Input ────────────────────────────────────────────────────────────────────

def _ids_field(**kwargs):
    return serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=MAX_ID),
        max_length=MAX_SCOPE_DOCUMENTS, **kwargs,
    )


class WorkspaceInput(serializers.Serializer):
    name = serializers.CharField(max_length=120)


class DocumentPatchInput(serializers.Serializer):
    title = serializers.CharField(max_length=255)


class UrlDocumentInput(serializers.Serializer):
    source_type = serializers.ChoiceField(choices=["url"])
    url = serializers.CharField(max_length=2048)
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    workspace_id = serializers.IntegerField(min_value=1, max_value=MAX_ID, required=False, allow_null=True)


class TextDocumentInput(serializers.Serializer):
    source_type = serializers.ChoiceField(choices=["text"])
    # Whitespace is content here; emptiness and length are checked by the view
    # against settings.RAG_MAX_TEXT_CHARS.
    text = serializers.CharField(trim_whitespace=False)
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    workspace_id = serializers.IntegerField(min_value=1, max_value=MAX_ID, required=False, allow_null=True)


class ConversationCreateInput(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    workspace_id = serializers.IntegerField(min_value=1, max_value=MAX_ID, required=False, allow_null=True)
    document_ids = _ids_field(required=False)


class ConversationPatchInput(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    document_ids = _ids_field(required=False)


class MessageInput(serializers.Serializer):
    content = serializers.CharField(max_length=MAX_QUESTION_CHARS)
    document_ids = _ids_field(required=False, allow_null=True)


class RunListQuery(serializers.Serializer):
    """Query parameters of GET retrieval/runs/ (ids are checked by the view)."""
    status = serializers.ChoiceField(choices=RetrievalRun.Status.values, required=False)
    source = serializers.ChoiceField(choices=RetrievalRun.Source.values, required=False)
    limit = serializers.IntegerField(min_value=1, max_value=RUN_LIST_MAX_LIMIT, required=False, default=RUN_LIST_DEFAULT_LIMIT)


class RunSummaryQuery(serializers.Serializer):
    days = serializers.IntegerField(min_value=1, max_value=SUMMARY_MAX_DAYS, required=False, default=SUMMARY_DEFAULT_DAYS)
    source = serializers.ChoiceField(choices=RetrievalRun.Source.values, required=False)


def validated(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


# ── Output ───────────────────────────────────────────────────────────────────

def workspace_payload(workspace, document_count=None, conversation_count=None):
    if document_count is None:
        document_count = getattr(workspace, "document_count", None)
    if document_count is None:
        document_count = workspace.documents.count()
    if conversation_count is None:
        conversation_count = getattr(workspace, "conversation_count", None)
    if conversation_count is None:
        conversation_count = workspace.conversations.count()
    return {
        "id": workspace.pk,
        "name": workspace.name,
        "is_default": workspace.is_default,
        "document_count": document_count,
        "conversation_count": conversation_count,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
    }


def document_source(document):
    """The original filename, the URL, or None for pasted text."""
    if document.source_type == "url":
        # Legacy URL rows kept the URL in `name` and never set source_url.
        return document.source_url or document.name
    if document.source_type == "text":
        return None
    return (document.metadata or {}).get("original_filename") or document.name


def has_original_file(document):
    # Fetched web pages are deliberately not served back: replaying
    # third-party HTML from this origin would be a stored-XSS vector.
    return document.source_type in FILE_SOURCE_TYPES and bool(document.source_path)


def document_error(document):
    if document.status != Document.Status.FAILED:
        return None
    return {
        "code": document.error_code or "ingestion_failed",
        "message": document.error_message or "Document ingestion failed. Retry ingestion.",
        "retryable": document.retryable,
        "stage": document.error_stage or None,
    }


def document_index(document):
    vector = document.current_index if document.current_index_id else None
    if document.status != Document.Status.READY or vector is None:
        return None
    return {
        "id": vector.pk,
        "method": vector.method,
        "embedding_model": (document.metadata or {}).get("embedding_model"),
        "created_at": vector.created_at,
    }


def document_payload(document):
    metadata = document.metadata or {}
    return {
        "id": document.pk,
        "workspace_id": document.workspace_id,
        "title": document.name,
        "source_type": document.source_type,
        "source": document_source(document),
        "mime_type": document.mime_type or MIME_BY_SOURCE_TYPE.get(document.source_type, ""),
        "file_size": document.file_size,
        "has_original_file": has_original_file(document),
        "status": document.status,
        "status_detail": document.status_detail,
        "progress": document.progress,
        "error": document_error(document),
        "page_count": metadata.get("page_count"),
        "chunk_count": metadata.get("chunk_count"),
        "char_count": metadata.get("char_count"),
        "index": document_index(document),
        "created_at": document.created_at,
        "updated_at": document.updated_at,
        "ingested_at": document.ingested_at,
    }


def stage_states(document):
    status = document.status
    if status == Document.Status.READY:
        current, state = None, "done"
    elif status == Document.Status.QUEUED:
        current, state = Document.Status.EXTRACTING, "pending"
    elif status == Document.Status.FAILED:
        current, state = (document.error_stage, "failed") if document.error_stage in STAGE_IDS else (Document.Status.EXTRACTING, "pending")
    else:
        current, state = status, "active"
    states = []
    reached = current is None
    for stage, label in INGESTION_STAGES:
        if stage == current:
            reached = True
            states.append({"id": stage, "label": label, "state": state})
        elif current is None or not reached:
            states.append({"id": stage, "label": label, "state": "done"})
        else:
            states.append({"id": stage, "label": label, "state": "pending"})
    return states


def ingestion_payload(document, job, can_retry):
    return {
        "document_id": document.pk,
        "status": document.status,
        "progress": document.progress,
        "status_detail": document.status_detail,
        "stages": stage_states(document),
        "job": {"id": str(job.pk), "status": job.status, "updated_at": job.updated_at} if job else None,
        "error": document_error(document),
        "can_retry": can_retry,
    }


def preview(text):
    text = " ".join((text or "").split())
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS - 1].rstrip() + "…"


def conversation_payload(session, message_count=None, last_message=None):
    if message_count is None:
        message_count = getattr(session, "message_count", None)
    if message_count is None:
        message_count = session.messages.count()
    if last_message is None:
        if hasattr(session, "last_message_content"):
            last_message = session.last_message_content or ""
        else:
            latest = session.messages.order_by("-created_at", "-id").values_list("content", flat=True).first()
            last_message = latest or ""
    return {
        "id": session.pk,
        "workspace_id": session.workspace_id,
        "title": session.title,
        "document_ids": sorted(document.pk for document in session.documents.all()),
        "message_count": message_count,
        "last_message_preview": preview(last_message),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def message_error(message):
    if message.status != ChatMessage.Status.FAILED:
        return None
    return {
        "code": message.error_code or "chat_failed",
        "message": message.error_message or "The answer could not be generated. Try again.",
        "retryable": message.retryable,
    }


def message_payload(message):
    turn = None
    if message.analysis_turn_id:
        turn = {"conversation_id": message.analysis_turn_id, "document_id": message.analysis_turn.document_id}
    return {
        "id": message.pk,
        "conversation_id": message.session_id,
        "role": message.role,
        "content": message.content,
        "status": message.status,
        "citations": message.citations or [],
        "retrieval": message.retrieval,
        "token_usage": message.token_usage,
        "latency_ms": message.latency_ms,
        "error": message_error(message),
        "analysis_turn": turn,
        "created_at": message.created_at,
    }


def job_is_live(job):
    return job is not None and job.status in (Job.Status.PENDING, Job.Status.PROCESSING)


# ── Retrieval runs (Phase 2) ─────────────────────────────────────────────────

def run_payload(run):
    """A run as listed: what happened, how long it took, what it cost."""
    provenance = run.provenance or {}
    usage = None
    if run.total_tokens is not None or run.prompt_tokens is not None or run.completion_tokens is not None:
        usage = {"prompt_tokens": run.prompt_tokens, "completion_tokens": run.completion_tokens, "total_tokens": run.total_tokens}
    error = None
    if run.status == RetrievalRun.Status.FAILED:
        error = {
            "code": run.error_code or "run_failed",
            "message": run.error_message or "The request failed.",
            "stage": run.error_stage or None,
        }
    return {
        "id": run.pk,
        "workspace_id": run.workspace_id,
        "conversation_id": run.conversation_id,
        "message_id": run.message_id,
        "source": run.source,
        "status": run.status,
        "query": {
            "original": run.query_original,
            "rewritten": run.query_rewritten or run.query_original,
            "rewrite_applied": run.rewrite_applied,
            "rewrite_reason": run.rewrite_reason or None,
        },
        "error": error,
        "latency_ms": {
            "total": run.total_ms, "rewrite": run.rewrite_ms, "retrieval": run.retrieval_ms,
            "rerank": run.rerank_ms, "generation": run.generation_ms, "first_token": run.first_token_ms,
        },
        "token_usage": usage,
        "candidate_count": run.candidate_count,
        "context_count": run.context_count,
        "cited_count": run.cited_count,
        "strategy": provenance.get("strategy"),
        "generation_model": provenance.get("generation_model"),
        "started_at": run.started_at,
        "created_at": run.created_at,
    }


def span_rows(spans):
    return [
        {
            "ordinal": span.ordinal, "parent_ordinal": span.parent_ordinal, "depth": span.depth,
            "name": span.name, "label": span.label, "status": span.status,
            "start_ms": span.start_ms, "duration_ms": span.duration_ms,
            "detail": span.detail, "error_code": span.error_code or None, "data": span.data or {},
        }
        for span in spans
    ]


def candidate_payload(candidate, text=None):
    document = candidate.document if candidate.document_id else None
    return {
        "rank": candidate.rank,
        "document_id": candidate.document_id,
        "document_title": (document.name if document is not None else "") or candidate.document_title,
        "document_available": document is not None,
        "index_version_id": candidate.index_version_id,
        "chunk_id": candidate.chunk_id,
        "page_number": candidate.page_start,
        "page_end": candidate.page_end,
        "char_start": candidate.char_start,
        "char_end": candidate.char_end,
        # The whole passage while its chunk exists, else the stored snippet.
        "text": text if text is not None else candidate.snippet,
        "retrieval_score": candidate.retrieval_score,
        "rerank_score": candidate.rerank_score,
        "selected_for_context": candidate.selected_for_context,
        "cited": candidate.cited,
        "citation_id": candidate.citation_id,
    }


def run_detail_payload(run, spans, candidates, texts=None):
    """The full trace: provenance, span tree, candidates."""
    texts = texts or {}
    return {
        **run_payload(run),
        "provenance": run.provenance or {},
        "spans": build_tree(span_rows(spans)),
        "candidates": [candidate_payload(candidate, texts.get(candidate.pk)) for candidate in candidates],
    }
