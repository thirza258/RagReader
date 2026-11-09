"""One chat turn as a stream of events (PRD §13–16).

`run_chat_turn` is the single producer behind both transports: the SSE view
forwards its events as they happen, `?stream=0` collects them. It persists as
it goes, so the answer is saved even if nobody is listening any more.

    message.created → stage(rewrite) → stage(retrieve)… → retrieval →
    stage(generate) → token… → message.completed        (or → error)
"""
import logging
import time
from dataclasses import dataclass

import numpy as np
from django.db import transaction
from django.utils import timezone

from ai_handler.llm import StreamResult
from common.constant import (
    CHAT_CANDIDATE_K, CHAT_CONTEXT_K, CHAT_HISTORY_MESSAGES, CHAT_PROMPT_VERSION,
)
from common.embeddings import embed_texts
from common.errors import PipelineError
from common.prompt_builder import cited_chat_messages, standalone_query_prompt
from evaluation.models import Chunk
from router.models import Conversation, ConversationHistory, DocumentVector
from workspace.errors import describe_exception
from workspace.models import ChatMessage, ChatSession
from workspace.serializers import message_payload
from workspace.services import index_cache
from workspace.services.citations import evidence, mark_cited
from workspace.services.ingestion import chat_engine, dense_engine_of

logger = logging.getLogger(__name__)

REWRITE_MAX_CHARS = 200
TITLE_MAX_CHARS = 80
REWRITE_PREFIXES = ("standalone query:", "search query:", "query:", "rewritten query:")
INTERRUPTED_MESSAGE = "The connection closed before the answer finished. Ask again to retry."


def _ms(since):
    return int(round((time.monotonic() - since) * 1000))


def stage_event(stage, status, detail="", duration_ms=None):
    return "stage", {"id": stage, "status": status, "detail": detail, "duration_ms": duration_ms}


def auto_title(question):
    line = " ".join((question or "").strip().splitlines()[0].split()) if (question or "").strip() else ""
    if len(line) <= TITLE_MAX_CHARS:
        return line or "New conversation"
    cut = line[:TITLE_MAX_CHARS - 1]
    if " " in cut[TITLE_MAX_CHARS // 2:]:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,.;:") + "…"


# ── Persistence ──────────────────────────────────────────────────────────────

def conversation_history(session):
    """The last CHAT_HISTORY_MESSAGES completed messages, oldest first."""
    rows = list(
        session.messages.filter(status=ChatMessage.Status.COMPLETE)
        .order_by("-created_at", "-id")[:CHAT_HISTORY_MESSAGES]
    )
    rows.reverse()
    return [{"role": row.role, "content": row.content} for row in rows]


def _create_messages(session, question):
    now = timezone.now()
    with transaction.atomic():
        first = not session.messages.exists()
        user_message = ChatMessage.objects.create(
            session=session, role=ChatMessage.Role.USER, content=question, status=ChatMessage.Status.COMPLETE,
        )
        assistant = ChatMessage.objects.create(
            session=session, role=ChatMessage.Role.ASSISTANT, content="", status=ChatMessage.Status.STREAMING,
        )
        updates = {"updated_at": now}
        if first and session.title_is_auto:
            updates["title"] = auto_title(question)
        ChatSession.objects.filter(pk=session.pk).update(**updates)
    return user_message, assistant


def _touch(session):
    ChatSession.objects.filter(pk=session.pk).update(updated_at=timezone.now())


def _fail(assistant, error, *, content, retrieval, latency_ms):
    ChatMessage.objects.filter(pk=assistant.pk).update(
        status=ChatMessage.Status.FAILED, content=content,
        error_code=error["code"], error_message=error["message"], retryable=bool(error["retryable"]),
        retrieval=retrieval, latency_ms=latency_ms, updated_at=timezone.now(),
    )
    assistant.refresh_from_db()


def _analysis_turn(user, document, query, answer, sources):
    """The legacy turn deep analysis is keyed by, as QueryView records it."""
    turn = Conversation.objects.create(
        user=user, document=document, query=query, response=answer,
        context="\n\n".join(source["text"] for source in sources),
    )
    ConversationHistory.objects.create(user=user, conversation=turn)
    return turn


# ── Rewrite ──────────────────────────────────────────────────────────────────

def rewrite_question(engine, question, history):
    """(search query, applied). Any problem keeps the original question."""
    try:
        raw = engine.llm.generate(standalone_query_prompt(question, history))
    except Exception:
        logger.warning("Query rewrite failed; searching with the original question", exc_info=True)
        return question, False
    candidate = (raw or "").strip()
    lowered = candidate.lower()
    for prefix in REWRITE_PREFIXES:
        if lowered.startswith(prefix):
            candidate = candidate[len(prefix):].strip()
            break
    candidate = candidate.strip().strip("\"'“”‘’`").strip()
    if not candidate or "\n" in candidate or "\r" in candidate or len(candidate) > REWRITE_MAX_CHARS:
        return question, False
    return candidate, candidate != question


# ── Retrieval ────────────────────────────────────────────────────────────────

@dataclass
class Retrieval:
    sources: list       # Evidence for the prompt, [n] order
    candidates: list    # RetrievalMetadata.candidates
    documents: list     # RetrievalMetadata.documents


def chat_index(engine, document):
    """`current_index`, else the newest ready index of the engine's method."""
    vector = document.current_index if document.current_index_id else None
    if vector is not None and vector.status == "ready" and vector.method == engine.method:
        return vector
    return (
        DocumentVector.objects.filter(document=document, status="ready", method=engine.method)
        .order_by("-created_at", "-id").first()
    )


def index_unavailable(document, reason="could not be loaded"):
    return PipelineError(
        "index_unavailable",
        f"The search index for “{document.name}” {reason}. Re-index the document and ask again.",
        retryable=False, http_status=409,
    )


def retrieve(engine, query, documents, timings):
    dense = dense_engine_of(engine)
    loaded = []
    for document in documents:
        vector = chat_index(engine, document)
        snapshot = index_cache.get_snapshot(engine, vector, dense.model) if vector is not None else None
        if snapshot is None:
            # Never built inline: an index build is minutes of embedding calls.
            raise index_unavailable(document)
        loaded.append((document, vector, snapshot))

    started = time.monotonic()
    query_vector = np.asarray(embed_texts(dense.client, [query], dense.model)[0], dtype=np.float32)
    timings["embed_query"] = _ms(started)
    query_vector = query_vector / (np.linalg.norm(query_vector) or 1.0)

    started = time.monotonic()
    pool = []
    for order, (document, vector, snapshot) in enumerate(loaded):
        if not len(snapshot):
            continue
        if snapshot.dimensions != query_vector.shape[0]:
            raise index_unavailable(document, "was built with a different embedding model")
        scores = snapshot.matrix @ query_vector
        depth = min(CHAT_CANDIDATE_K, len(scores))
        for index in np.argpartition(-scores, depth - 1)[:depth]:
            pool.append((float(scores[index]), order, int(index), document, vector, snapshot))
    # Highest score first; ties keep document order, then position.
    pool.sort(key=lambda item: (-item[0], item[1], item[2]))
    seen, kept = set(), []
    for item in pool:
        text = item[5].texts[item[2]]
        key = " ".join(text.split())
        if key in seen:
            continue  # The same passage twice would waste a context slot.
        seen.add(key)
        kept.append(item)
        if len(kept) == CHAT_CANDIDATE_K:
            break
    timings["search"] = _ms(started)

    context = kept[:CHAT_CONTEXT_K]
    chunk_ids = [item[5].chunk_ids[item[2]] for item in context]
    positions = dict(Chunk.objects.filter(pk__in=[pk for pk in chunk_ids if pk is not None]).values_list("pk", "metadata"))
    sources = [
        evidence(
            number, document=item[3], vector_id=item[4].pk, chunk_id=chunk_id,
            text=item[5].texts[item[2]], score=item[0], position=positions.get(chunk_id),
        )
        for number, (item, chunk_id) in enumerate(zip(context, chunk_ids), 1)
    ]
    candidates = [
        {"document_id": item[3].pk, "chunk_id": item[5].chunk_ids[item[2]],
         "retrieval_score": round(item[0], 6), "rank": rank}
        for rank, item in enumerate(kept, 1)
    ]
    used = [{"document_id": document.pk, "index_version_id": vector.pk} for document, vector, _ in loaded]
    return Retrieval(sources=sources, candidates=candidates, documents=used)


# ── The turn ─────────────────────────────────────────────────────────────────

def run_chat_turn(session, user, question, documents):
    """Yield (event name, data) for one question over READY `documents`."""
    started = time.monotonic()
    timings = {"rewrite": 0, "embed_query": None, "search": None, "first_token": None, "generation": None, "total": None}
    retrieval = {
        "pipeline": {
            "strategy": "dense", "embedding_model": None, "generation_model": None, "temperature": None,
            "candidate_k": CHAT_CANDIDATE_K, "top_k": CHAT_CONTEXT_K, "prompt_version": CHAT_PROMPT_VERSION,
        },
        "query": {"original": question, "rewritten": question, "rewrite_applied": False},
        "documents": [], "candidates": [], "candidate_count": 0, "context_count": 0, "cited_count": 0,
        "timings_ms": timings,
    }
    history = conversation_history(session)
    user_message, assistant = _create_messages(session, question)

    stage, parts, saved = "rewrite", [], False
    try:
        yield "message.created", {"user_message": message_payload(user_message), "assistant_message": message_payload(assistant)}
        engine = chat_engine()
        dense = dense_engine_of(engine)
        retrieval["pipeline"].update(
            embedding_model=dense.model, generation_model=engine.llm.model, temperature=engine.llm.temperature,
        )

        if history:
            yield stage_event("rewrite", "running", "Rewriting the question with the conversation context")
            began = time.monotonic()
            rewritten, applied = rewrite_question(engine, question, history)
            timings["rewrite"] = _ms(began)
            retrieval["query"].update(rewritten=rewritten, rewrite_applied=applied)
            if applied:
                yield stage_event("rewrite", "completed", f"Searching for: {rewritten}", timings["rewrite"])
            else:
                yield stage_event("rewrite", "skipped", "Searching with the original question", timings["rewrite"])
        else:
            yield stage_event("rewrite", "skipped", "First question in the conversation", 0)

        stage = "retrieve"
        noun = "document" if len(documents) == 1 else "documents"
        yield stage_event("retrieve", "running", f"Searching {len(documents)} {noun}")
        began = time.monotonic()
        found = retrieve(engine, retrieval["query"]["rewritten"], documents, timings)
        retrieval.update(
            documents=found.documents, candidates=found.candidates,
            candidate_count=len(found.candidates), context_count=len(found.sources),
        )
        yield stage_event("retrieve", "completed", f"Retrieved {len(found.candidates)} candidates", _ms(began))
        yield "retrieval", {
            "candidate_count": len(found.candidates), "context_count": len(found.sources),
            "citations": found.sources,
        }

        stage = "generate"
        yield stage_event("generate", "running", f"Writing the answer from {len(found.sources)} sources")
        began, result = time.monotonic(), None
        for item in engine.llm.stream_chat(cited_chat_messages(question, found.sources, history)):
            if isinstance(item, StreamResult):
                result = item
                continue
            if timings["first_token"] is None:
                timings["first_token"] = _ms(started)
            parts.append(item)
            yield "token", {"delta": item}
        timings["generation"] = _ms(began)
        answer = "".join(parts)
        if result is not None and result.model:
            retrieval["pipeline"]["generation_model"] = result.model
        citations = mark_cited(found.sources, answer)
        retrieval["cited_count"] = sum(1 for source in citations if source["cited"])

        # Persist before the closing events: a client that leaves after the
        # last token must not cost the user a finished answer.
        stage = "finish"
        turn = None
        if len(documents) == 1:
            turn = _analysis_turn(user, documents[0], retrieval["query"]["rewritten"], answer, found.sources)
        timings["total"] = _ms(started)
        assistant.content = answer
        assistant.status = ChatMessage.Status.COMPLETE
        assistant.citations = citations
        assistant.retrieval = retrieval
        assistant.token_usage = result.usage if result is not None else None
        assistant.latency_ms = timings["total"]
        assistant.analysis_turn = turn
        assistant.error_code, assistant.error_message, assistant.retryable = "", "", False
        assistant.save()
        _touch(session)
        saved = True
        yield stage_event(
            "generate", "completed",
            f"Cited {retrieval['cited_count']} of {len(citations)} sources", timings["generation"],
        )
        yield "message.completed", {"message": message_payload(assistant)}
    except GeneratorExit:
        # The consumer stopped iterating (a WSGI client disconnect). Under
        # ASGI the producer runs to completion instead; see services/sse.py.
        if not saved:
            timings["total"] = _ms(started)
            _fail(assistant, {"code": "stream_interrupted", "message": INTERRUPTED_MESSAGE, "retryable": True},
                  content="".join(parts), retrieval=retrieval, latency_ms=timings["total"])
        raise
    except Exception as exc:
        _status, error = describe_exception(exc)
        timings["total"] = _ms(started)
        failed_stage = "generate" if stage == "finish" else stage
        _fail(assistant, error, content="".join(parts), retrieval=retrieval, latency_ms=timings["total"])
        _touch(session)
        yield stage_event(failed_stage, "failed", error["message"])
        yield "error", {"error": {**error, "stage": failed_stage}, "message": message_payload(assistant)}
