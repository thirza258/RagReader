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

Since Phase 3 a turn runs with a pipeline version (the conversation's
pipeline, latest version at question time; services/pipelines.py): its
strategy, depths and reranker drive `services.retrieval.run_retrieval`, and
its generation model and temperature drive the rewrite and the answer.
"""
import logging
import time
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from ai_handler.llm import StreamResult
from common.constant import CHAT_HISTORY_MESSAGES
from common.prompt_builder import cited_chat_messages, standalone_query_prompt
from router.models import Conversation, ConversationHistory
from workspace.errors import describe_exception
from workspace.models import ChatMessage, ChatSession, RetrievalRun
from workspace.serializers import message_payload
from workspace.services import llms, pipelines, tracing
from workspace.services import runs as run_store
from workspace.services.citations import evidence, mark_cited
from workspace.services.ingestion import chat_engine
from workspace.services.retrieval import (  # noqa: F401 - chat_index/index_unavailable re-exported
    INDEX_LOAD_SPANS, chat_index, index_unavailable, retrieval_parameters, run_retrieval,
)

logger = logging.getLogger(__name__)

REWRITE_MAX_CHARS = 200
TITLE_MAX_CHARS = 80
REWRITE_PREFIXES = ("standalone query:", "search query:", "query:", "rewritten query:")
INTERRUPTED_MESSAGE = "The connection closed before the answer finished. Ask again to retry."
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

def rewrite_question(llm, question, history, outcome=None):
    """(search query, applied). Any problem keeps the original question.

    `llm` is the turn's generation LLM. `outcome`, when given, receives
    `reason` for the trace: `rewritten`, `unchanged`, `unusable` or `failed`.
    """
    outcome = {} if outcome is None else outcome
    try:
        raw = llm.generate(standalone_query_prompt(question, history))
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
    rerank: dict | None = None  # services.retrieval.RetrievalResult.rerank
    rerank_ms: int | None = None


def _score(value):
    return round(float(value), 6) if value is not None else None


def retrieve(engine, query, documents, timings, config, tracer=None, indexes=None):
    """Run the pipeline's retrieval over `documents` and shape it for the turn.

    `tracer` receives the retrieval spans; `indexes`, a list the caller owns,
    receives one provenance entry per document as its index is resolved.
    """
    measured = {}
    try:
        found = run_retrieval(query, documents, config, engine=engine, tracer=tracer, indexes=indexes, timings=measured)
    finally:
        # The message's timings keep their Phase 1 keys; reranking time is
        # recorded on the run (`rerank_ms`) and its span.
        for key in ("embed_query", "search"):
            if key in measured:
                timings[key] = measured[key]
    context_size = len(found.context)
    sources = []
    for number, candidate in enumerate(found.context, 1):
        source = evidence(
            number, document=candidate.document, vector_id=candidate.index_version_id, chunk_id=candidate.chunk_id,
            text=candidate.text, score=candidate.retrieval_score, position=candidate.position_metadata,
        )
        source["rerank_score"] = _score(candidate.rerank_score)
        sources.append(source)
    candidates = [
        {"document_id": candidate.document.pk, "chunk_id": candidate.chunk_id,
         "retrieval_score": round(candidate.retrieval_score, 6), "rank": candidate.rank,
         "dense_score": _score(candidate.dense_score), "bm25_score": _score(candidate.bm25_score),
         "fused_score": _score(candidate.fused_score), "rerank_score": _score(candidate.rerank_score),
         "retrieval_rank": candidate.retrieval_rank}
        for candidate in found.candidates
    ]
    ranked = [
        {
            "rank": candidate.rank, "retrieval_rank": candidate.retrieval_rank,
            "document": candidate.document, "index_version_id": candidate.index_version_id,
            "chunk_id": candidate.chunk_id, "retrieval_score": candidate.retrieval_score,
            "dense_score": candidate.dense_score, "bm25_score": candidate.bm25_score,
            "fused_score": candidate.fused_score, "rerank_score": candidate.rerank_score,
            "text": candidate.text, "position": candidate.position_metadata,
            "selected_for_context": candidate.rank <= context_size,
            "citation_id": candidate.rank if candidate.rank <= context_size else None, "cited": False,
        }
        for candidate in found.candidates
    ]
    used = [{"document_id": entry.document.pk, "index_version_id": entry.vector.pk} for entry in found.loaded]
    return Retrieval(sources=sources, candidates=candidates, documents=used, ranked=ranked, rerank=found.rerank,
                     rerank_ms=measured.get("rerank"))


# ── The run record (PRD §20, §32) ────────────────────────────────────────────

def _reranker_provenance(config, rerank):
    """Null without a reranker; else what was configured and what happened."""
    spec = config.get("reranker")
    if not spec:
        return None
    rerank = rerank or {}
    return {
        "provider": spec.get("provider"), "model": spec.get("model"),
        "applied": bool(rerank.get("applied")), "fallback": bool(rerank.get("fallback")),
        "error_code": rerank.get("error_code"),
    }


def _provenance(tracer, retrieval, run, history, document_count):
    pipeline, generation, config = retrieval["pipeline"], run["generation"], run["config"]
    return {
        "schema_version": 1,
        "timestamp": tracer.started_at.isoformat(),
        "strategy": pipeline["strategy"],
        "retrieval_parameters": {
            **retrieval_parameters(config),
            "query_rewrite": bool(history), "history_messages": len(history),
            "history_limit": CHAT_HISTORY_MESSAGES,
        },
        "embedding_model": pipeline["embedding_model"],
        "reranker": _reranker_provenance(config, run["rerank"]),
        # The model that answered (null until one did) and the configured one;
        # they differ when the free-model fallback was used.
        "generation_model": generation["model"],
        "configured_generation_model": generation["configured_model"],
        "fallback_used": generation["fallback"],
        "generation_parameters": {"temperature": pipeline["temperature"], "stream": True},
        "prompt_version": pipeline["prompt_version"],
        "index_versions": run["indexes"][:run_store.MAX_RUN_INDEX_VERSIONS],
        "index_version_count": document_count,
        # Phase 3: the pipeline version, with its full configuration, so the
        # run stays reproducible after the pipeline is edited or deleted.
        "pipeline": pipelines.snapshot(run["version"]),
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
                    "retrieval": run["retrieval_ms"], "rerank": run["rerank_ms"],
                    "generation": timings["generation"], "first_token": timings["first_token"],
                },
                usage=result.usage if result is not None else None,
                counts={"candidates": retrieval["candidate_count"], "context": retrieval["context_count"],
                        "cited": retrieval["cited_count"]},
                started_at=tracer.started_at, spans=spans, candidates=candidates,
                pipeline_version=run["version"],
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

def _version_ref(version):
    """`retrieval.pipeline_version`: which pipeline version answered (Phase 3)."""
    return {"id": version.pk, "pipeline_id": version.pipeline_id, "name": version.pipeline.name, "number": version.number}


def run_chat_turn(session, user, question, documents, pipeline_version=None):
    """Yield (event name, data) for one question over READY `documents`.

    `pipeline_version` defaults to the latest version of the conversation's
    pipeline (the workspace default when it names none).
    """
    started = time.monotonic()
    tracer = tracing.new_tracer("chat.turn", "Chat turn", origin=started)
    if pipeline_version is None:
        pipeline_version = pipelines.session_pipeline(session)[1]
    config = pipeline_version.config
    timings = {"rewrite": 0, "embed_query": None, "search": None, "first_token": None, "generation": None, "total": None}
    retrieval = {
        "pipeline": {
            "strategy": config["strategy"], "embedding_model": config["embedding_model"],
            "generation_model": config["generation_model"], "temperature": config["temperature"],
            "candidate_k": config["candidate_k"], "top_k": config["top_k"], "prompt_version": config["prompt_version"],
        },
        "query": {"original": question, "rewritten": question, "rewrite_applied": False},
        "documents": [], "candidates": [], "candidate_count": 0, "context_count": 0, "cited_count": 0,
        "timings_ms": timings,
        "run_id": None,
        "pipeline_version_id": pipeline_version.pk,
        "pipeline_version": _version_ref(pipeline_version),
        "rerank": None,
    }
    # What the run records beyond the message's retrieval metadata.
    run = {
        "rewrite_reason": "", "retrieval_ms": None, "rerank_ms": None, "indexes": [], "ranked": [], "rerank": None,
        "generation": {"model": None, "configured_model": config["generation_model"], "fallback": False},
        "config": config, "version": pipeline_version,
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
        # The engine's own LLM for its own model (the default pipeline), else
        # a shared client for the pipeline's model; the temperature is per call.
        llm = llms.generation_llm(engine, config["generation_model"])

        if history:
            yield stage_event("rewrite", "running", "Rewriting the question with the conversation context")
            with tracer.span("rewrite", "Query rewrite", history_messages=len(history)) as span:
                began = time.monotonic()
                outcome = {}
                rewritten, applied = rewrite_question(llm, question, history, outcome)
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
            found = retrieve(engine, retrieval["query"]["rewritten"], documents, timings, config,
                             tracer=tracer, indexes=run["indexes"])
            span.set(candidates=len(found.candidates), context=len(found.sources))
        run["retrieval_ms"] = _ms(began)
        run["ranked"] = found.ranked
        run["rerank"], run["rerank_ms"] = found.rerank, found.rerank_ms
        retrieval.update(
            documents=found.documents, candidates=found.candidates,
            candidate_count=len(found.candidates), context_count=len(found.sources),
            rerank=found.rerank,
        )
        detail = f"Retrieved {len(found.candidates)} candidates"
        if found.rerank is not None:
            detail += (f", reranked to {len(found.sources)}" if found.rerank["applied"]
                       else "; the reranker failed, so the fused order was kept")
        yield stage_event("retrieve", "completed", detail, run["retrieval_ms"])
        yield "retrieval", {
            "candidate_count": len(found.candidates), "context_count": len(found.sources),
            "citations": found.sources,
        }

        stage = "generate"
        yield stage_event("generate", "running", f"Writing the answer from {len(found.sources)} sources")
        began = time.monotonic()
        with tracer.span("generate", "Generation", configured_model=config["generation_model"]) as span:
            waiting = tracer.start("generate.first_token", "Time to first token")
            messages = cited_chat_messages(question, found.sources, history)
            for item in llm.stream_chat(messages, temperature=config["temperature"]):
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
