"""One chat turn as a stream of events (PRD §13–16).

`run_chat_turn` is the single producer behind both transports: the SSE view
forwards its events as they happen, `?stream=0` collects them. It persists as
it goes, so the answer is saved even if nobody is listening any more.

    message.created → stage(rewrite) → stage(retrieve)… → retrieval →
    stage(generate) → token… → message.completed        (or → error)

Every turn is also traced (services/tracing.py) and recorded as a
`RetrievalRun` — completed or failed — before the closing events, so a client
that leaves early does not lose the trace either. Recording is guarded: if it
fails, the answer is still delivered and saved, just without a run id.
"""
import contextlib
import logging
import time
from dataclasses import dataclass, field

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
from workspace.models import ChatMessage, ChatSession, RetrievalRun
from workspace.serializers import message_payload
from workspace.services import index_cache, tracing
from workspace.services import runs as run_store
from workspace.services.citations import evidence, mark_cited
from workspace.services.ingestion import chat_engine, dense_engine_of

logger = logging.getLogger(__name__)

REWRITE_MAX_CHARS = 200
TITLE_MAX_CHARS = 80
REWRITE_PREFIXES = ("standalone query:", "search query:", "query:", "rewritten query:")
INTERRUPTED_MESSAGE = "The connection closed before the answer finished. Ask again to retry."
# Per-document index loads get their own span up to this many documents; the
# rest are only counted on the "Load indexes" span (keeps traces bounded).
INDEX_LOAD_SPANS = 25
REWRITE_DETAILS = {
    "first_question": "First question in the conversation",
    "rewritten": "Rewritten with the conversation context",
    "unchanged": "The rewrite matched the question",
    "unusable": "The rewrite was unusable; searched with the question as asked",
    "failed": "The rewrite failed; searched with the question as asked",
}


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

def rewrite_question(engine, question, history, outcome=None):
    """(search query, applied). Any problem keeps the original question.

    `outcome`, when given, receives `reason` for the trace: `rewritten`,
    `unchanged`, `unusable` or `failed`.
    """
    outcome = {} if outcome is None else outcome
    try:
        raw = engine.llm.generate(standalone_query_prompt(question, history))
    except Exception:
        logger.warning("Query rewrite failed; searching with the original question", exc_info=True)
        outcome["reason"] = "failed"
        return question, False
    candidate = (raw or "").strip()
    lowered = candidate.lower()
    for prefix in REWRITE_PREFIXES:
        if lowered.startswith(prefix):
            candidate = candidate[len(prefix):].strip()
            break
    candidate = candidate.strip().strip("\"'“”‘’`").strip()
    if not candidate or "\n" in candidate or "\r" in candidate or len(candidate) > REWRITE_MAX_CHARS:
        outcome["reason"] = "unusable"
        return question, False
    applied = candidate != question
    outcome["reason"] = "rewritten" if applied else "unchanged"
    return candidate, applied


# ── Retrieval ────────────────────────────────────────────────────────────────

@dataclass
class Retrieval:
    sources: list       # Evidence for the prompt, [n] order
    candidates: list    # RetrievalMetadata.candidates
    documents: list     # RetrievalMetadata.documents
    ranked: list = field(default_factory=list)  # every candidate, with text and position, for the run


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


def _index_entry(document, vector):
    """A provenance record of the index a document is searched with (§20)."""
    return {
        "document_id": document.pk,
        "document_title": document.name,
        "index_version_id": vector.pk if vector is not None else None,
        "method": vector.method if vector is not None else None,
        "created_at": vector.created_at.isoformat() if vector is not None and vector.created_at else None,
        "embedding_model": (document.metadata or {}).get("embedding_model"),
        "loaded": False,
    }


def _int_ids(values):
    return [value for value in values if isinstance(value, int) and not isinstance(value, bool)]


def retrieve(engine, query, documents, timings, tracer=None, indexes=None):
    """Dense retrieval over `documents`.

    `tracer` receives the load/embed/search/select spans; `indexes`, a list
    the caller owns, receives one provenance entry per document as its index
    is resolved, so it is complete up to the point of a failure.
    """
    tracer = tracer if tracer is not None else tracing.NullTracer()
    indexes = [] if indexes is None else indexes
    dense = dense_engine_of(engine)
    loaded = []
    with tracer.span("retrieve.load_indexes", "Load indexes", documents=len(documents)) as group:
        hits = misses = 0
        for position, document in enumerate(documents):
            vector = chat_index(engine, document)
            entry = _index_entry(document, vector)
            if len(indexes) < run_store.MAX_RUN_INDEX_VERSIONS:
                indexes.append(entry)
            scope = (
                tracer.span("index.load", f"Load index: {document.name}", document_id=document.pk, index_version_id=entry["index_version_id"])
                if position < INDEX_LOAD_SPANS else contextlib.nullcontext(tracing.Span("index.load"))
            )
            with scope as span:
                if vector is None:
                    span.describe("No ready index")
                    raise index_unavailable(document)
                snapshot, hit = index_cache.fetch_snapshot(engine, vector, dense.model)
                span.set(cache="hit" if hit else "miss")
                if snapshot is None:
                    span.describe("Could not be loaded")
                    # Never built inline: an index build is minutes of embedding calls.
                    raise index_unavailable(document)
                span.set(chunks=len(snapshot)).describe("Cache hit" if hit else "Loaded from disk")
            hits, misses = hits + hit, misses + (not hit)
            group.set(cache_hits=hits, cache_misses=misses)
            entry["loaded"] = True
            loaded.append((document, vector, snapshot))

    with tracer.span("retrieve.embed_query", "Query embedding", model=dense.model) as span:
        started = time.monotonic()
        query_vector = np.asarray(embed_texts(dense.client, [query], dense.model)[0], dtype=np.float32)
        timings["embed_query"] = _ms(started)
        span.set(dimensions=int(query_vector.shape[0]) if query_vector.ndim else 0)
    query_vector = query_vector / (np.linalg.norm(query_vector) or 1.0)

    started = time.monotonic()
    with tracer.span("retrieve.search", "Vector search", similarity="cosine") as span:
        pool, scored = [], 0
        for order, (document, vector, snapshot) in enumerate(loaded):
            if not len(snapshot):
                continue
            if snapshot.dimensions != query_vector.shape[0]:
                raise index_unavailable(document, "was built with a different embedding model")
            scores = snapshot.matrix @ query_vector
            scored += len(scores)
            depth = min(CHAT_CANDIDATE_K, len(scores))
            for index in np.argpartition(-scores, depth - 1)[:depth]:
                pool.append((float(scores[index]), order, int(index), document, vector, snapshot))
        span.set(chunks_scored=scored, pooled=len(pool))

    with tracer.span("retrieve.select", "Merge and select") as span:
        # Highest score first; ties keep document order, then position.
        pool.sort(key=lambda item: (-item[0], item[1], item[2]))
        seen, kept, duplicates = set(), [], 0
        for item in pool:
            text = item[5].texts[item[2]]
            key = " ".join(text.split())
            if key in seen:
                duplicates += 1
                continue  # The same passage twice would waste a context slot.
            seen.add(key)
            kept.append(item)
            if len(kept) == CHAT_CANDIDATE_K:
                break
        timings["search"] = _ms(started)

        context = kept[:CHAT_CONTEXT_K]
        all_ids = [item[5].chunk_ids[item[2]] for item in kept]
        # Positions for every candidate, not only the context: the trace
        # opens any of them in the reader.
        positions = dict(Chunk.objects.filter(pk__in=_int_ids(all_ids)).values_list("pk", "metadata"))
        chunk_ids = all_ids[:len(context)]
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
        ranked = [
            {
                "rank": rank, "document": item[3], "index_version_id": item[4].pk, "chunk_id": chunk_id,
                "retrieval_score": item[0], "rerank_score": None, "text": item[5].texts[item[2]],
                "position": positions.get(chunk_id), "selected_for_context": rank <= len(context),
                "citation_id": rank if rank <= len(context) else None, "cited": False,
            }
            for rank, (item, chunk_id) in enumerate(zip(kept, all_ids), 1)
        ]
        span.set(candidates=len(kept), duplicates_skipped=duplicates, context=len(context))
    used = [{"document_id": document.pk, "index_version_id": vector.pk} for document, vector, _ in loaded]
    return Retrieval(sources=sources, candidates=candidates, documents=used, ranked=ranked)


# ── The run record (PRD §20, §32) ────────────────────────────────────────────

def _provenance(tracer, retrieval, run, history, document_count):
    pipeline, generation = retrieval["pipeline"], run["generation"]
    return {
        "schema_version": 1,
        "timestamp": tracer.started_at.isoformat(),
        "strategy": pipeline["strategy"],
        "retrieval_parameters": {
            "candidate_k": pipeline["candidate_k"], "context_k": pipeline["top_k"],
            "similarity": "cosine", "deduplicate": True,
            "query_rewrite": bool(history), "history_messages": len(history),
            "history_limit": CHAT_HISTORY_MESSAGES,
        },
        "embedding_model": pipeline["embedding_model"],
        "reranker": None,
        # The model that answered (null until one did) and the configured one;
        # they differ when the free-model fallback was used.
        "generation_model": generation["model"],
        "configured_generation_model": generation["configured_model"],
        "fallback_used": generation["fallback"],
        "generation_parameters": {"temperature": pipeline["temperature"], "stream": True},
        "prompt_version": pipeline["prompt_version"],
        "index_versions": run["indexes"][:run_store.MAX_RUN_INDEX_VERSIONS],
        "index_version_count": document_count,
    }


def _record_run(*, tracer, session, user, assistant, question, retrieval, timings, run, history, documents,
                status, error=None, error_stage="", result=None, citations=None):
    """Store the turn as a RetrievalRun; its id, or None if that failed (logged)."""
    try:
        cited = {source["citation_id"] for source in (citations or []) if source.get("cited")}
        candidates = [{**item, "cited": item["citation_id"] in cited} for item in run["ranked"]]
        query = retrieval["query"]
        spans = tracer.export()
        with transaction.atomic():  # a failed write must not poison the connection
            saved = run_store.save_run(
                user=user, workspace=session.workspace, conversation=session, message=assistant,
                source=RetrievalRun.Source.CHAT, status=status,
                query_original=question, query_rewritten=query["rewritten"],
                rewrite_applied=query["rewrite_applied"], rewrite_reason=run["rewrite_reason"],
                error=error, error_stage=error_stage,
                provenance=_provenance(tracer, retrieval, run, history, len(documents)),
                latency={
                    "total": timings["total"], "rewrite": timings["rewrite"] if history else None,
                    "retrieval": run["retrieval_ms"], "rerank": None,
                    "generation": timings["generation"], "first_token": timings["first_token"],
                },
                usage=result.usage if result is not None else None,
                counts={"candidates": retrieval["candidate_count"], "context": retrieval["context_count"],
                        "cited": retrieval["cited_count"]},
                started_at=tracer.started_at, spans=spans, candidates=candidates,
            )
        return saved.pk
    except Exception:
        logger.warning("Could not record the retrieval run; the answer is not affected", exc_info=True)
        return None


def _attach_run(assistant, retrieval, run_id):
    """Adds `run_id` to the stored and in-memory retrieval metadata."""
    if run_id is None:
        return
    try:
        with transaction.atomic():
            ChatMessage.objects.filter(pk=assistant.pk).update(retrieval={**retrieval, "run_id": run_id})
        retrieval["run_id"] = run_id
    except Exception:
        logger.warning("Could not link run %s to message %s", run_id, assistant.pk, exc_info=True)


# ── The turn ─────────────────────────────────────────────────────────────────

def run_chat_turn(session, user, question, documents):
    """Yield (event name, data) for one question over READY `documents`."""
    started = time.monotonic()
    tracer = tracing.new_tracer("chat.turn", "Chat turn", origin=started)
    timings = {"rewrite": 0, "embed_query": None, "search": None, "first_token": None, "generation": None, "total": None}
    retrieval = {
        "pipeline": {
            "strategy": "dense", "embedding_model": None, "generation_model": None, "temperature": None,
            "candidate_k": CHAT_CANDIDATE_K, "top_k": CHAT_CONTEXT_K, "prompt_version": CHAT_PROMPT_VERSION,
        },
        "query": {"original": question, "rewritten": question, "rewrite_applied": False},
        "documents": [], "candidates": [], "candidate_count": 0, "context_count": 0, "cited_count": 0,
        "timings_ms": timings,
        "run_id": None,
    }
    # What the run records beyond the message's retrieval metadata.
    run = {
        "rewrite_reason": "", "retrieval_ms": None, "indexes": [], "ranked": [],
        "generation": {"model": None, "configured_model": None, "fallback": False},
    }
    with tracer.span("prepare", "Load history and save the question"):
        history = conversation_history(session)
        user_message, assistant = _create_messages(session, question)
    record = dict(tracer=tracer, session=session, user=user, assistant=assistant, question=question,
                  retrieval=retrieval, timings=timings, run=run, history=history, documents=documents)

    stage, parts, saved, result = "rewrite", [], False, None
    try:
        yield "message.created", {"user_message": message_payload(user_message), "assistant_message": message_payload(assistant)}
        engine = chat_engine()
        dense = dense_engine_of(engine)
        retrieval["pipeline"].update(
            embedding_model=dense.model, generation_model=engine.llm.model, temperature=engine.llm.temperature,
        )
        run["generation"]["configured_model"] = engine.llm.model

        if history:
            yield stage_event("rewrite", "running", "Rewriting the question with the conversation context")
            with tracer.span("rewrite", "Query rewrite", history_messages=len(history)) as span:
                began = time.monotonic()
                outcome = {}
                rewritten, applied = rewrite_question(engine, question, history, outcome)
                timings["rewrite"] = _ms(began)
                run["rewrite_reason"] = reason = outcome.get("reason", "")
                span.set(applied=applied, reason=reason).describe(REWRITE_DETAILS.get(reason, ""))
                if reason == "unusable":
                    span.skip()
                elif reason == "failed":
                    # Recovered (the question is searched as asked), but shown.
                    span.fail("rewrite_failed")
            retrieval["query"].update(rewritten=rewritten, rewrite_applied=applied)
            if applied:
                yield stage_event("rewrite", "completed", f"Searching for: {rewritten}", timings["rewrite"])
            else:
                yield stage_event("rewrite", "skipped", "Searching with the original question", timings["rewrite"])
        else:
            run["rewrite_reason"] = "first_question"
            with tracer.span("rewrite", "Query rewrite") as span:
                span.skip(REWRITE_DETAILS["first_question"])
            yield stage_event("rewrite", "skipped", "First question in the conversation", 0)

        stage = "retrieve"
        noun = "document" if len(documents) == 1 else "documents"
        yield stage_event("retrieve", "running", f"Searching {len(documents)} {noun}")
        began = time.monotonic()
        with tracer.span("retrieve", "Retrieval", documents=len(documents)) as span:
            found = retrieve(engine, retrieval["query"]["rewritten"], documents, timings,
                             tracer=tracer, indexes=run["indexes"])
            span.set(candidates=len(found.candidates), context=len(found.sources))
        run["retrieval_ms"] = _ms(began)
        run["ranked"] = found.ranked
        retrieval.update(
            documents=found.documents, candidates=found.candidates,
            candidate_count=len(found.candidates), context_count=len(found.sources),
        )
        yield stage_event("retrieve", "completed", f"Retrieved {len(found.candidates)} candidates", run["retrieval_ms"])
        yield "retrieval", {
            "candidate_count": len(found.candidates), "context_count": len(found.sources),
            "citations": found.sources,
        }

        stage = "generate"
        yield stage_event("generate", "running", f"Writing the answer from {len(found.sources)} sources")
        began = time.monotonic()
        with tracer.span("generate", "Generation", configured_model=engine.llm.model) as span:
            waiting = tracer.start("generate.first_token", "Time to first token")
            for item in engine.llm.stream_chat(cited_chat_messages(question, found.sources, history)):
                if isinstance(item, StreamResult):
                    result = item
                    continue
                if timings["first_token"] is None:
                    timings["first_token"] = _ms(started)
                    tracer.finish(waiting)
                parts.append(item)
                yield "token", {"delta": item}
            timings["generation"] = _ms(began)
            if result is not None:
                run["generation"].update(model=result.model or None, fallback=bool(getattr(result, "fallback", False)))
                span.set(model=result.model, fallback=run["generation"]["fallback"], finish_reason=result.finish_reason)
            span.set(characters=sum(len(part) for part in parts))
        answer = "".join(parts)

        with tracer.span("citations", "Citation parsing") as span:
            if result is not None and result.model:
                retrieval["pipeline"]["generation_model"] = result.model
            citations = mark_cited(found.sources, answer)
            retrieval["cited_count"] = sum(1 for source in citations if source["cited"])
            span.set(sources=len(citations), cited=retrieval["cited_count"])

        # Persist before the closing events: a client that leaves after the
        # last token must not cost the user a finished answer (or its run).
        stage = "finish"
        with tracer.span("persist", "Save the answer") as span:
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
            span.set(analysis_turn=turn is not None)
        tracer.close()
        run_id = _record_run(**record, status=RetrievalRun.Status.COMPLETED, result=result, citations=citations)
        _attach_run(assistant, retrieval, run_id)
        yield stage_event(
            "generate", "completed",
            f"Cited {retrieval['cited_count']} of {len(citations)} sources", timings["generation"],
        )
        yield "message.completed", {"message": message_payload(assistant), "run_id": run_id}
    except GeneratorExit:
        # The consumer stopped iterating (a WSGI client disconnect). Under
        # ASGI the producer runs to completion instead; see services/sse.py.
        if not saved:
            timings["total"] = _ms(started)
            error = {"code": "stream_interrupted", "message": INTERRUPTED_MESSAGE, "retryable": True}
            tracer.close(error=error["code"])
            run_id = _record_run(**record, status=RetrievalRun.Status.FAILED, error=error,
                                 error_stage="generate" if stage == "finish" else stage, result=result)
            if run_id is not None:
                retrieval["run_id"] = run_id
            _fail(assistant, error, content="".join(parts), retrieval=retrieval, latency_ms=timings["total"])
        raise
    except Exception as exc:
        _status, error = describe_exception(exc)
        timings["total"] = _ms(started)
        failed_stage = "generate" if stage == "finish" else stage
        tracer.close(error=error["code"])
        run_id = _record_run(**record, status=RetrievalRun.Status.FAILED, error=error,
                             error_stage=failed_stage, result=result)
        if run_id is not None:
            retrieval["run_id"] = run_id
        _fail(assistant, error, content="".join(parts), retrieval=retrieval, latency_ms=timings["total"])
        _touch(session)
        yield stage_event(failed_stage, "failed", error["message"])
        yield "error", {"error": {**error, "stage": failed_stage}, "message": message_payload(assistant), "run_id": run_id}
