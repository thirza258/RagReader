"""Retrieval for workspace questions: dense, BM25, hybrid and hybrid + rerank (PRD §17–18).

`run_retrieval(query, documents, config, ...)` ranks the passages of every
READY document in scope with one pipeline configuration and returns ranked
candidates carrying every score that produced the ranking. Chat calls it per
question; evaluation (Phase 4) can call it without generating anything.

Strategies:

* **dense** — Phase 1 exactly: cosine similarity of the query embedding with
  every passage of each loaded index snapshot; the top `candidate_k` of each
  document are pooled, sorted by score (ties: document order, then position),
  identical passages are kept once and the first `candidate_k` remain.
* **bm25** — BM25Okapi over the *union* of the in-scope passages (one IDF and
  average length, so scores compare across documents), built with the shared
  tokenizer (`sparse_rag.tokenize`, English stop words removed) and cached per
  set of index versions (`index_cache.fetch_bm25`). Passages with score ≤ 0
  (no query term) are not candidates. Same pooling and de-duplication.
* **hybrid** — both rankings (each de-duplicated and cut to `candidate_k`)
  fused into one:
  - `weighted`: each retriever's raw scores are min-max normalised over the
    passages being fused (all equal → 1), then
    `hybrid_weight × dense + (1 − hybrid_weight) × bm25`. A retriever with
    weight 0 contributes no passages, so a weight of 1 (or 0) gives exactly
    the dense (or BM25) ranking.
  - `rrf`: `Σ 1 / (rrf_k + rank)` over the rankings that returned the passage.
  Ties: document order, then position. The first `candidate_k` remain.
* **hybrid_rerank** — hybrid, then a reranker (services/rerankers.py) scores
  every candidate and they are reordered by that score (ties keep the fused
  order). Any reranker failure keeps the fused order: the `retrieve.rerank`
  span is marked `fallback` with the error code and the question goes on.

The first `top_k` candidates (after reranking) are the context.
`retrieval_score` is the score the passage was retrieved by — cosine
(dense), BM25 (bm25) or the fused score (hybrid strategies); the components
`dense_score`, `bm25_score` and `fused_score` are kept for every candidate the
strategy computed them for, with `retrieval_rank` (before reranking) and
`rank` (final).

Spans (under the caller's `retrieve` span): `retrieve.load_indexes` (one
`index.load` per document), then `retrieve.embed_query` + `retrieve.search`
(dense strategies), `retrieve.bm25` (BM25 strategies), `retrieve.fusion`
(hybrid strategies), `retrieve.select`, and `retrieve.rerank`
(hybrid_rerank). The dense strategy emits exactly Phase 1's spans and data.
"""
import contextlib
import logging
import math
import time
from dataclasses import dataclass, field

import numpy as np

from common.embeddings import embed_texts
from common.errors import PipelineError
from evaluation.models import Chunk
from router.models import DocumentVector
from workspace.services import index_cache, tracing
from workspace.services import runs as run_store
from workspace.services.ingestion import chat_engine, dense_engine_of
from workspace.services.pipelines import BM25_STRATEGIES, DENSE_STRATEGIES, FUSION_STRATEGIES, RERANK_STRATEGIES
from workspace.services.rerankers import reranker_for

logger = logging.getLogger(__name__)

# Per-document index loads get their own span up to this many documents; the
# rest are only counted on the "Load indexes" span (keeps traces bounded).
INDEX_LOAD_SPANS = 25
SIMILARITY = {"dense": "cosine", "bm25": "bm25", "hybrid": "cosine+bm25", "hybrid_rerank": "cosine+bm25"}


def _ms(since):
    return int(round((time.monotonic() - since) * 1000))


@dataclass
class Loaded:
    """One document in scope with the index snapshot it is searched with."""
    order: int
    document: object
    vector: object
    snapshot: object


@dataclass
class Candidate:
    """One ranked passage and every score that placed it."""
    order: int          # its document's position in scope
    position: int       # its passage's position in the snapshot
    document: object
    vector: object
    snapshot: object
    retrieval_score: float = 0.0
    dense_score: float | None = None
    bm25_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None
    retrieval_rank: int = 0
    rank: int = 0
    position_metadata: dict | None = None

    @property
    def text(self):
        return self.snapshot.texts[self.position]

    @property
    def chunk_id(self):
        return self.snapshot.chunk_ids[self.position]

    @property
    def index_version_id(self):
        return self.vector.pk


@dataclass
class RetrievalResult:
    candidates: list            # final order (after reranking)
    context: list               # the first top_k of `candidates`
    loaded: list                # Loaded, in scope order
    duplicates_skipped: int = 0
    # {"provider", "model", "applied", "fallback", "error_code", "duration_ms"}; None without a reranker.
    rerank: dict | None = None
    timings: dict = field(default_factory=dict)


# ── Indexes ──────────────────────────────────────────────────────────────────

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


def embedding_mismatch(message):
    return PipelineError("embedding_model_mismatch", message, retryable=False, http_status=409)


def index_entry(document, vector):
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


def load_indexes(engine, documents, tracer, indexes):
    """Loaded snapshots for `documents`, in order; `index_unavailable` if one cannot load.

    `indexes`, a list the caller owns, receives one provenance entry per
    document as its index is resolved, so it is complete up to a failure.
    The chat path never builds an index inline (minutes of embedding calls).
    """
    dense = dense_engine_of(engine)
    loaded = []
    with tracer.span("retrieve.load_indexes", "Load indexes", documents=len(documents)) as group:
        hits = misses = 0
        for position, document in enumerate(documents):
            vector = chat_index(engine, document)
            entry = index_entry(document, vector)
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
                    raise index_unavailable(document)
                span.set(chunks=len(snapshot)).describe("Cache hit" if hit else "Loaded from disk")
            hits, misses = hits + hit, misses + (not hit)
            group.set(cache_hits=hits, cache_misses=misses)
            entry["loaded"] = True
            loaded.append(Loaded(order=position, document=document, vector=vector, snapshot=snapshot))
    return loaded


# ── Ranking primitives (pure) ────────────────────────────────────────────────

def text_key(text):
    """Identical passages (up to whitespace) are kept once."""
    return " ".join((text or "").split())


def pool(loaded, scores, depth, keep=None):
    """Each document's top `depth` passages: (score, order, position, Loaded).

    `scores[order]` holds one score per passage of that document; `keep`
    filters which passages may be candidates at all (BM25: score > 0).
    """
    items = []
    for entry in loaded:
        values = scores.get(entry.order)
        if values is None or not len(values):
            continue
        allowed = np.arange(len(values)) if keep is None else np.flatnonzero(keep(values))
        if not len(allowed):
            continue
        subset = values[allowed]
        top = min(depth, len(allowed))
        for index in np.argpartition(-subset, top - 1)[:top]:
            position = int(allowed[index])
            items.append((float(values[position]), entry.order, position, entry))
    return items


def unique_ranking(items, depth):
    """(kept, duplicates): highest score first (ties: document order, then
    position), identical passages once, at most `depth`."""
    items = sorted(items, key=lambda item: (-item[0], item[1], item[2]))
    seen, kept, duplicates = set(), [], 0
    for item in items:
        key = text_key(item[3].snapshot.texts[item[2]])
        if key in seen:
            duplicates += 1
            continue  # The same passage twice would waste a context slot.
        seen.add(key)
        kept.append(item)
        if len(kept) == depth:
            break
    return kept, duplicates


def _normalised(values):
    """Min-max to [0, 1]; all equal → 1."""
    low, high = min(values), max(values)
    if not high > low:
        return [1.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def fuse(dense_ranking, bm25_ranking, *, method, hybrid_weight, rrf_k, dense_scores, bm25_scores):
    """Fused (score, order, position, Loaded, dense raw, bm25 raw), best first.

    `dense_ranking`/`bm25_ranking` come from `unique_ranking`; `*_scores` map
    document order → raw scores of every passage, so each fused passage gets
    both components even when only one retriever returned it.
    """
    members = {}
    use_dense = method == "rrf" or hybrid_weight > 0
    use_bm25 = method == "rrf" or hybrid_weight < 1
    for name, ranking, used in (("dense", dense_ranking, use_dense), ("bm25", bm25_ranking, use_bm25)):
        if not used:
            continue
        for rank, item in enumerate(ranking, 1):
            entry = members.setdefault(text_key(item[3].snapshot.texts[item[2]]), {"item": item, "ranks": {}})
            entry["ranks"][name] = rank
    entries = list(members.values())
    if not entries:
        return []
    dense_raw = [float(dense_scores[entry["item"][1]][entry["item"][2]]) for entry in entries]
    bm25_raw = [float(bm25_scores[entry["item"][1]][entry["item"][2]]) for entry in entries]
    if method == "rrf":
        fused = [sum(1.0 / (rrf_k + rank) for rank in entry["ranks"].values()) for entry in entries]
    else:
        weight = float(hybrid_weight)
        fused = [
            weight * dense + (1.0 - weight) * bm25
            for dense, bm25 in zip(_normalised(dense_raw), _normalised(bm25_raw))
        ]
    rows = [
        (score, entry["item"][1], entry["item"][2], entry["item"][3], dense, bm25)
        for score, entry, dense, bm25 in zip(fused, entries, dense_raw, bm25_raw)
    ]
    rows.sort(key=lambda row: (-row[0], row[1], row[2]))
    return rows


def rerank(reranker, query, candidates):
    """Reorder `candidates` by the reranker's scores (stable: ties keep their order)."""
    scores = reranker.score(query, [candidate.text for candidate in candidates])
    if len(scores) != len(candidates) or not all(isinstance(score, float) and math.isfinite(score) for score in scores):
        raise PipelineError("reranker_invalid_response", "The reranker returned an unusable score list.", retryable=True, http_status=502)
    for candidate, score in zip(candidates, scores):
        candidate.rerank_score = score
    order = sorted(range(len(candidates)), key=lambda index: (-candidates[index].rerank_score, index))
    return [candidates[index] for index in order]


# ── The retrieval run ────────────────────────────────────────────────────────

def _fallback_code(exc):
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) and code else "reranker_failed"


def run_retrieval(query, documents, config, *, engine=None, tracer=None, indexes=None, timings=None):
    """Rank the passages of `documents` for `query` with a pipeline `config`.

    `config` is a pipeline version's configuration (strategy, fusion,
    hybrid_weight, rrf_k, candidate_k, top_k, reranker, embedding_model).
    `timings` (a dict the caller owns) receives `embed_query`, `search` and
    `rerank` in milliseconds. Raises `index_unavailable` or
    `embedding_model_mismatch`; never fails because of the reranker.
    """
    engine = engine if engine is not None else chat_engine()
    tracer = tracer if tracer is not None else tracing.NullTracer()
    indexes = [] if indexes is None else indexes
    timings = {} if timings is None else timings
    strategy = config["strategy"]
    candidate_k, top_k = int(config["candidate_k"]), int(config["top_k"])
    uses_dense, uses_bm25 = strategy in DENSE_STRATEGIES, strategy in BM25_STRATEGIES

    loaded = load_indexes(engine, documents, tracer, indexes)

    dense_scores = {}
    if uses_dense:
        dense = dense_engine_of(engine)
        if config.get("embedding_model") and config["embedding_model"] != dense.model:
            raise embedding_mismatch(
                f"This pipeline embeds questions with {config['embedding_model']}, but the indexes are searched "
                f"with {dense.model}. Edit the pipeline's embedding model."
            )
        with tracer.span("retrieve.embed_query", "Query embedding", model=dense.model) as span:
            started = time.monotonic()
            query_vector = np.asarray(embed_texts(dense.client, [query], dense.model)[0], dtype=np.float32)
            timings["embed_query"] = _ms(started)
            span.set(dimensions=int(query_vector.shape[0]) if query_vector.ndim else 0)
        query_vector = query_vector / (np.linalg.norm(query_vector) or 1.0)

    started = time.monotonic()
    dense_pool, bm25_pool, bm25_scores = [], [], {}
    if uses_dense:
        with tracer.span("retrieve.search", "Vector search", similarity="cosine") as span:
            scored = 0
            for entry in loaded:
                if not len(entry.snapshot):
                    continue
                if entry.snapshot.dimensions != query_vector.shape[0]:
                    raise index_unavailable(entry.document, "was built with a different embedding model")
                dense_scores[entry.order] = entry.snapshot.matrix @ query_vector
                scored += len(dense_scores[entry.order])
            dense_pool = pool(loaded, dense_scores, candidate_k)
            span.set(chunks_scored=scored, pooled=len(dense_pool))

    if uses_bm25:
        with tracer.span("retrieve.bm25", "BM25 keyword search") as span:
            snapshots = [entry.snapshot for entry in loaded]
            locations = {entry.vector.pk: entry.vector.vectorstore_location for entry in loaded}
            bm25, hit = index_cache.fetch_bm25(snapshots, locations)
            by_vector = bm25.scores(query, snapshots)
            for entry in loaded:
                bm25_scores[entry.order] = by_vector[entry.snapshot.vector_id]
            bm25_pool = pool(loaded, bm25_scores, candidate_k, keep=lambda values: values > 0)
            matched = int(sum(int((values > 0).sum()) for values in bm25_scores.values()))
            span.set(cache="hit" if hit else "miss", corpus_chunks=bm25.size, query_terms=len(bm25.query_tokens(query)),
                     chunks_scored=sum(len(values) for values in bm25_scores.values()), matched=matched, pooled=len(bm25_pool))
            span.describe("Cache hit" if hit else "Built over the documents in scope")

    duplicates = 0
    if strategy in FUSION_STRATEGIES:
        with tracer.span("retrieve.fusion", "Fusion", method=config["fusion"]) as span:
            dense_ranking, dense_dupes = unique_ranking(dense_pool, candidate_k)
            bm25_ranking, bm25_dupes = unique_ranking(bm25_pool, candidate_k)
            duplicates = dense_dupes + bm25_dupes
            fused = fuse(dense_ranking, bm25_ranking, method=config["fusion"], hybrid_weight=config["hybrid_weight"],
                         rrf_k=config["rrf_k"], dense_scores=dense_scores, bm25_scores=bm25_scores)
            span.set(**({"rrf_k": config["rrf_k"]} if config["fusion"] == "rrf" else {"hybrid_weight": config["hybrid_weight"]}))
            span.set(dense_candidates=len(dense_ranking), bm25_candidates=len(bm25_ranking), fused=len(fused))

    with tracer.span("retrieve.select", "Merge and select") as span:
        if strategy in FUSION_STRATEGIES:
            kept = fused[:candidate_k]
            candidates = [
                Candidate(order=row[1], position=row[2], document=row[3].document, vector=row[3].vector, snapshot=row[3].snapshot,
                          retrieval_score=row[0], fused_score=row[0], dense_score=row[4], bm25_score=row[5])
                for row in kept
            ]
        else:
            kept, duplicates = unique_ranking(dense_pool if uses_dense else bm25_pool, candidate_k)
            candidates = []
            for score, order, position, entry in kept:
                candidate = Candidate(order=order, position=position, document=entry.document, vector=entry.vector,
                                      snapshot=entry.snapshot, retrieval_score=score)
                if uses_dense:
                    candidate.dense_score = score
                else:
                    candidate.bm25_score = score
                candidates.append(candidate)
        for rank, candidate in enumerate(candidates, 1):
            candidate.retrieval_rank = candidate.rank = rank
        timings["search"] = _ms(started)
        context_size = min(top_k, len(candidates))
        # Positions for every candidate, not only the context: the trace
        # opens any of them in the reader.
        wanted = [candidate.chunk_id for candidate in candidates]
        wanted = [value for value in wanted if isinstance(value, int) and not isinstance(value, bool)]
        positions = dict(Chunk.objects.filter(pk__in=wanted).values_list("pk", "metadata")) if wanted else {}
        for candidate in candidates:
            candidate.position_metadata = positions.get(candidate.chunk_id)
        span.set(candidates=len(candidates), duplicates_skipped=duplicates, context=context_size)

    rerank_info = None
    if strategy in RERANK_STRATEGIES:
        spec = config.get("reranker") or {}
        rerank_info = {"provider": spec.get("provider"), "model": spec.get("model"), "applied": False,
                       "fallback": False, "error_code": None, "duration_ms": None}
        with tracer.span("retrieve.rerank", "Reranking", provider=spec.get("provider"), model=spec.get("model"),
                         candidates=len(candidates)) as span:
            began = time.monotonic()
            try:
                if candidates:
                    candidates = rerank(reranker_for(spec), query, candidates)
                    for rank, candidate in enumerate(candidates, 1):
                        candidate.rank = rank
                rerank_info["applied"] = True
                moved = sum(1 for candidate in candidates if candidate.rank != candidate.retrieval_rank)
                span.set(reordered=moved).describe(f"Reranked {len(candidates)} candidates")
            except Exception as exc:
                code = _fallback_code(exc)
                logger.warning("Reranking with %s failed (%s); keeping the fused order", spec, code, exc_info=True)
                for candidate in candidates:
                    candidate.rerank_score = None
                    candidate.rank = candidate.retrieval_rank
                candidates.sort(key=lambda candidate: candidate.rank)
                rerank_info.update(fallback=True, error_code=code)
                span.fallback(code, "The reranker failed; kept the fused order")
            rerank_info["duration_ms"] = timings["rerank"] = _ms(began)

    return RetrievalResult(
        candidates=candidates, context=candidates[:min(top_k, len(candidates))], loaded=loaded,
        duplicates_skipped=duplicates, rerank=rerank_info, timings=timings,
    )


def retrieval_parameters(config):
    """Provenance `retrieval_parameters` (§20) a configuration implies (without history)."""
    strategy = config["strategy"]
    parameters = {
        "candidate_k": config["candidate_k"], "context_k": config["top_k"],
        "similarity": SIMILARITY.get(strategy, strategy), "deduplicate": True,
    }
    if strategy in FUSION_STRATEGIES:
        parameters["fusion"] = config["fusion"]
        if config["fusion"] == "rrf":
            parameters["rrf_k"] = config["rrf_k"]
        else:
            parameters["hybrid_weight"] = config["hybrid_weight"]
    return parameters
