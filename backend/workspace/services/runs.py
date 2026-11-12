"""Persisted retrieval runs and the reliability numbers built from them (PRD §32, §49).

`save_run` stores one run with its span rows and candidates. It is called
from the request's producer (the chat turn) inside its own savepoint, and the
caller treats any failure as "no trace": a run is diagnostic, never a reason
to lose an answer.

`reliability_summary` reports, for one workspace and window: run counts,
failure rates overall and by stage, latency percentiles, token totals and
ingestion success. Percentiles are computed in Python (the test database is
SQLite, which has no percentile function) with linear interpolation between
closest ranks — the definition of numpy's default and PostgreSQL's
`percentile_cont` — over completed runs only.
"""
import math
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from router.models import Document, Job
from workspace.models import RetrievalCandidate, RetrievalRun, RetrievalSpan
from workspace.services import tracing

# Retention guards: no run stores an unbounded payload.
MAX_RUN_CANDIDATES = 50
MAX_RUN_INDEX_VERSIONS = 200
SNIPPET_CHARS = 300
# Latency percentiles read at most this many of the newest completed runs.
LATENCY_SAMPLE_MAX = 10000

LATENCY_FIELDS = (("total", "total_ms"), ("retrieval", "retrieval_ms"), ("generation", "generation_ms"), ("first_token", "first_token_ms"))
# error_stage → the §49 metric it counts towards.
STAGE_METRICS = {"retrieve": "retrieval", "generate": "generation"}


# ── Storing ──────────────────────────────────────────────────────────────────

def _int_or_none(value):
    """A non-negative int from an id or offset; anything else becomes None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        return None
    return number if 0 <= number < 2 ** 63 else None


def _ms(value):
    return None if value is None else max(0, int(round(value)))


def _score(value):
    if value is None:
        return None
    number = float(value)
    return round(number, 6) if math.isfinite(number) else None


def save_run(*, user, workspace, source, status, query_original, conversation=None, message=None,
             query_rewritten="", rewrite_applied=False, rewrite_reason="", error=None, error_stage="",
             provenance=None, latency=None, usage=None, counts=None, started_at=None,
             spans=(), candidates=()):
    """Create a run with its spans and (at most MAX_RUN_CANDIDATES) candidates.

    `latency` maps total/rewrite/retrieval/rerank/generation/first_token to
    milliseconds; `usage` is a token-usage dict; `spans` are rows from
    `Tracer.export()`; each candidate is a dict with rank, document,
    index_version_id, chunk_id, retrieval_score, rerank_score,
    selected_for_context, cited, citation_id, position and text.
    """
    latency, usage, counts, error = latency or {}, usage or {}, counts or {}, error or {}
    prompt, completion, total = (_int_or_none(usage.get(key)) for key in ("prompt_tokens", "completion_tokens", "total_tokens"))
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    run = RetrievalRun.objects.create(
        user=user, workspace=workspace, conversation=conversation, message=message,
        source=source, status=status,
        error_stage=(error_stage or "")[:16], error_code=(error.get("code") or "")[:80],
        error_message=error.get("message") or "",
        query_original=query_original or "", query_rewritten=query_rewritten or "",
        rewrite_applied=bool(rewrite_applied), rewrite_reason=(rewrite_reason or "")[:32],
        provenance=provenance or {},
        total_ms=_ms(latency.get("total")), rewrite_ms=_ms(latency.get("rewrite")),
        retrieval_ms=_ms(latency.get("retrieval")), rerank_ms=_ms(latency.get("rerank")),
        generation_ms=_ms(latency.get("generation")), first_token_ms=_ms(latency.get("first_token")),
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=total,
        candidate_count=max(0, int(counts.get("candidates") or 0)),
        context_count=max(0, int(counts.get("context") or 0)),
        cited_count=max(0, int(counts.get("cited") or 0)),
        started_at=started_at or timezone.now(),
    )
    RetrievalSpan.objects.bulk_create([
        RetrievalSpan(
            run=run, ordinal=row["ordinal"], parent_ordinal=row["parent_ordinal"], depth=row["depth"],
            name=row["name"], label=row["label"], status=row["status"],
            start_ms=row["start_ms"], duration_ms=row["duration_ms"],
            detail=row["detail"], error_code=row["error_code"], data=row["data"],
        )
        for row in list(spans)[:tracing.MAX_SPANS]
    ])
    rows = []
    for candidate in list(candidates)[:MAX_RUN_CANDIDATES]:
        document = candidate.get("document")
        position = candidate.get("position") or {}
        rows.append(RetrievalCandidate(
            run=run, rank=max(1, int(candidate["rank"])),
            document=document, document_title=(getattr(document, "name", "") or "")[:255],
            index_version_id=_int_or_none(candidate.get("index_version_id")),
            chunk_id=_int_or_none(candidate.get("chunk_id")),
            retrieval_score=_score(candidate.get("retrieval_score")),
            rerank_score=_score(candidate.get("rerank_score")),
            selected_for_context=bool(candidate.get("selected_for_context")),
            cited=bool(candidate.get("cited")),
            citation_id=_int_or_none(candidate.get("citation_id")),
            page_start=_int_or_none(position.get("page_start")), page_end=_int_or_none(position.get("page_end")),
            char_start=_int_or_none(position.get("char_start")), char_end=_int_or_none(position.get("char_end")),
            snippet=(candidate.get("text") or "")[:SNIPPET_CHARS],
        ))
    RetrievalCandidate.objects.bulk_create(rows)
    return run


# ── Reliability (§49) ────────────────────────────────────────────────────────

def percentile(values, p):
    """The p-th percentile (0–100) of the non-null `values`, or None if there are none.

    Linear interpolation between closest ranks: with n values sorted
    ascending, position (n - 1) · p / 100 is interpolated between its two
    neighbours. One value is its own percentile; [100, 200, 300, 400] has
    p50 = 250 and p95 = 385.
    """
    if not 0 <= p <= 100:
        raise ValueError("p must be between 0 and 100")
    data = sorted(float(value) for value in values if value is not None)
    if not data:
        return None
    position = (len(data) - 1) * p / 100
    lower, upper = math.floor(position), math.ceil(position)
    value = data[lower] if lower == upper else data[lower] + (data[upper] - data[lower]) * (position - lower)
    return round(value, 1)


def rate(part, whole):
    return round(part / whole, 4) if whole else None


def _latency(values):
    present = [value for value in values if value is not None]
    return {"p50": percentile(present, 50), "p95": percentile(present, 95), "count": len(present)}


def run_window(user, workspace, *, days, source=None, now=None):
    since = (now or timezone.now()) - timedelta(days=days)
    runs = RetrievalRun.objects.filter(user=user, workspace=workspace, started_at__gte=since)
    if source:
        runs = runs.filter(source=source)
    return runs, since


def reliability_summary(user, workspace, *, days, source=None, now=None):
    runs, since = run_window(user, workspace, days=days, source=source, now=now)
    totals = runs.aggregate(
        total=Count("id"),
        completed=Count("id", filter=Q(status=RetrievalRun.Status.COMPLETED)),
        failed=Count("id", filter=Q(status=RetrievalRun.Status.FAILED)),
        failed_retrieval=Count("id", filter=Q(status=RetrievalRun.Status.FAILED, error_stage="retrieve")),
        failed_generation=Count("id", filter=Q(status=RetrievalRun.Status.FAILED, error_stage="generate")),
        sum_prompt=Sum("prompt_tokens"),
        sum_completion=Sum("completion_tokens"),
        sum_total=Sum("total_tokens"),
        runs_with_usage=Count("id", filter=Q(total_tokens__isnull=False)),
    )
    total, failed = totals["total"], totals["failed"]
    other = failed - totals["failed_retrieval"] - totals["failed_generation"]

    sample = list(
        runs.filter(status=RetrievalRun.Status.COMPLETED).order_by("-started_at", "-id")
        .values_list(*(field for _key, field in LATENCY_FIELDS))[:LATENCY_SAMPLE_MAX]
    )
    latency = {"sample_size": len(sample)}
    for position, (key, _field) in enumerate(LATENCY_FIELDS):
        latency[key] = _latency(row[position] for row in sample)

    with_usage = totals["runs_with_usage"]
    return {
        "workspace_id": workspace.pk,
        "days": days,
        "source": source,
        "since": since,
        "runs": {"total": total, "completed": totals["completed"], "failed": failed},
        "failure_rate": rate(failed, total),
        "failures_by_stage": {
            "retrieval": {"count": totals["failed_retrieval"], "rate": rate(totals["failed_retrieval"], total)},
            "generation": {"count": totals["failed_generation"], "rate": rate(totals["failed_generation"], total)},
            "other": {"count": other, "rate": rate(other, total)},
        },
        "latency_ms": latency,
        "tokens": {
            "prompt": totals["sum_prompt"] or 0,
            "completion": totals["sum_completion"] or 0,
            "total": totals["sum_total"] or 0,
            "runs_with_usage": with_usage,
            "average_per_run": round((totals["sum_total"] or 0) / with_usage, 1) if with_usage else None,
        },
        "ingestion": ingestion_summary(user, workspace, since),
    }


def ingestion_summary(user, workspace, since):
    """Documents in the workspace by state, plus ingestion attempts in the window.

    Legacy documents that the Phase 1 backfill marked `not_indexed` never ran
    through ingestion, so they are reported apart and are not failures.
    """
    documents = Document.objects.filter(user=user, workspace=workspace)
    counts = documents.aggregate(
        total=Count("id"),
        ready=Count("id", filter=Q(status=Document.Status.READY)),
        failed=Count("id", filter=Q(status=Document.Status.FAILED) & ~Q(error_code="not_indexed")),
        not_indexed=Count("id", filter=Q(status=Document.Status.FAILED, error_code="not_indexed")),
    )
    in_progress = counts["total"] - counts["ready"] - counts["failed"] - counts["not_indexed"]
    finished = counts["ready"] + counts["failed"]
    attempts = Job.objects.filter(
        user=user, kind=Job.Kind.INGEST, document__workspace=workspace, created_at__gte=since,
    ).aggregate(
        total=Count("id"),
        succeeded=Count("id", filter=Q(status=Job.Status.READY)),
        failed=Count("id", filter=Q(status=Job.Status.FAILED)),
    )
    attempts_finished = attempts["succeeded"] + attempts["failed"]
    return {
        "documents": counts["total"],
        "ready": counts["ready"],
        "failed": counts["failed"],
        "in_progress": in_progress,
        "not_indexed": counts["not_indexed"],
        "success_rate": rate(counts["ready"], finished),
        "failure_rate": rate(counts["failed"], finished),
        "attempts": {
            "total": attempts["total"],
            "succeeded": attempts["succeeded"],
            "failed": attempts["failed"],
            "failure_rate": rate(attempts["failed"], attempts_finished),
        },
    }
