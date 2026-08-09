"""Candidate pooling: build a pseudo-ground-truth chunk set with RRF.

Instead of asking the user to hand-pick the relevant chunks, run the same
query through every retrieval method and fuse the ranked lists with
Reciprocal Rank Fusion. Chunks that several independent retrievers rank
highly float to the top; chunks only one method likes sink.

This is the TREC-style pooling idea: no single retriever defines relevance,
the consensus of all of them does.
"""
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RRF_K = 60
DEFAULT_TOP_N = 10


@dataclass
class PipelineResult:
    """Ranked retrieval result from a single pipeline."""
    pipeline_name: str
    ranked_chunks: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass
class PooledResult:
    """Final output of CandidatePooler.pool()."""
    rrf_ranked_chunks: list[dict[str, Any]]   # RRF-merged, best-first
    rrf_chunk_ids: list[Any]                  # convenience: IDs only
    per_pipeline: dict[str, PipelineResult]   # raw results keyed by name
    query: str = ""
    optimized_query: str = ""


# ── RRF implementation ───────────────────────────────────────────────────────

def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    k: int = DEFAULT_RRF_K,
    id_key: str = "chunk_id",
    names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Standard RRF over multiple ranked lists of chunk dicts.

    Score formula: sum(1 / (k + rank_i))  for each list i that contains
    the chunk, where rank_i is 1-based.

    Args:
        ranked_lists: Each element is an ordered list of chunk dicts.
                      Each dict must contain `id_key`.
        k:            RRF constant (default 60, per the original paper).
        id_key:       Dict key used to identify a chunk.
        names:        Optional label per ranked list. When given, each merged
                      chunk carries a `sources` list recording which pipeline
                      found it and at what rank.

    Returns:
        Single merged list, sorted by descending RRF score.
        Each dict is the original chunk dict enriched with `rrf_score`
        (and `sources` when `names` is supplied).
    """
    scores: dict[Any, float] = {}
    chunk_map: dict[Any, dict[str, Any]] = {}   # id → first chunk dict seen
    sources: dict[Any, list[dict[str, Any]]] = {}

    for list_idx, ranked_list in enumerate(ranked_lists):
        name = names[list_idx] if names and list_idx < len(names) else None

        for rank_0, chunk in enumerate(ranked_list):
            cid = chunk.get(id_key)
            if cid is None:
                logger.warning(f"Chunk missing '{id_key}' key — skipped: {chunk}")
                continue

            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank_0 + 1)

            # Keep the first-seen copy of the chunk payload; later pipelines
            # may have slightly different score fields but the text is the same.
            if cid not in chunk_map:
                chunk_map[cid] = chunk

            if name is not None:
                sources.setdefault(cid, []).append({
                    "pipeline": name,
                    "rank": rank_0 + 1,
                    "score": chunk.get("score"),
                })

    merged = []
    # Sort by score, then by id so ties are stable rather than dict-order.
    ordered = sorted(scores.items(), key=lambda x: (-x[1], str(x[0])))
    for cid, rrf_score in ordered:
        entry = dict(chunk_map[cid])  # shallow copy — don't mutate originals
        entry["rrf_score"] = round(rrf_score, 6)
        if names is not None:
            entry["sources"] = sources.get(cid, [])
        merged.append(entry)

    return merged


# ── CandidatePooler ──────────────────────────────────────────────────────────

class CandidatePooler:
    """
    Retrieves candidates from every registered pipeline, fuses them with RRF,
    and returns the merged ranking as a pseudo-ground-truth for evaluation.

    Register one pipeline *per retrieval method*. Registering the same method
    under several LLMs would count that retriever more than once in the RRF
    sum — the LLM does not influence which chunks come back.

    Usage
    -----
    pooler = build_default_pooler(top_n=10)
    result = pooler.pool(query="What is X?", username="alice")
    ground_truth_ids = set(result.rrf_chunk_ids)
    """

    def __init__(
        self,
        k: int = DEFAULT_RRF_K,
        top_n: int | None = DEFAULT_TOP_N,
        depth: int | None = None,
    ):
        """
        Args:
            k:     RRF constant. Higher → more weight to mid-rank hits.
            top_n: If set, truncate the final RRF list to the top-N chunks.
            depth: How many candidates to pull from each retriever. Defaults to
                   at least `top_n` — a pool shallower than the cut would be
                   decided by whichever methods happened to run.
        """
        self.k = k
        self.top_n = top_n
        self.depth = depth if depth is not None else max(top_n or 0, DEFAULT_TOP_N)
        self._pipelines: dict[str, Any] = {}

    # ── Registration ────────────────────────────────────────────────────────

    def register(self, name: str, pipeline: Any) -> "CandidatePooler":
        """Register a pipeline under a unique name. Returns self for chaining."""
        if name in self._pipelines:
            logger.warning(f"CandidatePooler: overwriting existing pipeline '{name}'")
        self._pipelines[name] = pipeline
        return self

    def unregister(self, name: str) -> None:
        self._pipelines.pop(name, None)

    @property
    def pipeline_names(self) -> list[str]:
        return list(self._pipelines.keys())

    # ── Index readiness ──────────────────────────────────────────────────────

    @staticmethod
    def _has_index_in_memory(pipeline: Any) -> bool:
        """True when the pipeline's engine already holds an index in memory.

        Each engine stores its corpus differently — Dense/Sparse on `documents`,
        Hybrid on `_documents` plus two sub-engines — so probe all of them
        rather than assuming one shape.
        """
        rag = getattr(pipeline, "rag", None)
        if rag is None:
            return False

        for attr in ("documents", "_documents"):
            if getattr(rag, attr, None):
                return True

        dense = getattr(rag, "dense_engine", None)
        return bool(dense is not None and getattr(dense, "documents", None))

    def _ensure_ready(self, name: str, pipeline: Any, username: str) -> None:
        """Load the index into memory if it isn't there yet."""
        if self._has_index_in_memory(pipeline):
            return
        logger.info(f"[{name}] index not in memory — calling init({username})...")
        pipeline.init(username)

    # ── Core retrieval ───────────────────────────────────────────────────────

    def _retrieve_from_pipeline(
        self,
        name: str,
        pipeline: Any,
        query: str,
        username: str | None = None,
    ) -> PipelineResult:
        """Retrieve for one pipeline, bypassing LLM generation entirely."""
        from rag.rag_service import apply_retrieval_depth

        try:
            if username:
                self._ensure_ready(name, pipeline, username)

            # Engines are process-wide singletons whose depth the analysis
            # sidebar also sets. Pin it here so a previous run's Top-K can't
            # decide how deep the pool goes.
            apply_retrieval_depth(pipeline, self.depth)

            ranked = pipeline.rag.retrieve(query) or []
            logger.info(f"[{name}] retrieved {len(ranked)} chunks.")
            return PipelineResult(pipeline_name=name, ranked_chunks=ranked)

        except Exception as e:
            logger.error(f"[{name}] retrieval failed: {e}", exc_info=True)
            return PipelineResult(pipeline_name=name, ranked_chunks=[], error=str(e))

    def _optimize_query(self, query: str) -> str:
        """Rewrite the query once and share it across every pipeline.

        Pooling should isolate the *retrievers* as the only variable, so all
        of them must see identical input. Optimising per pipeline would also
        cost one LLM call each.
        """
        for name, pipeline in self._pipelines.items():
            try:
                optimized = pipeline.optimize_query(query)
                if optimized:
                    return optimized
            except Exception as e:
                logger.warning(f"[{name}] query optimization failed: {e}")
        return query

    # ── Public API ───────────────────────────────────────────────────────────

    def pool(
        self,
        query: str,
        username: str | None = None,
        optimize: bool = True,
        top_n: int | None = None,
    ) -> PooledResult:
        """
        Retrieve from all registered pipelines and fuse results with RRF.

        Args:
            query:    The user / evaluation query.
            username: Owner of the index. When given, each pipeline is
                      initialised on demand before retrieving.
            optimize: Rewrite the query once (one LLM call) and use that same
                      string for every pipeline.
            top_n:    Override self.top_n for this call only.

        Returns:
            PooledResult with rrf_ranked_chunks and per-pipeline raw results.
        """
        if not self._pipelines:
            raise RuntimeError("No pipelines registered. Call .register() first.")

        optimized_query = self._optimize_query(query) if optimize else query

        per_pipeline: dict[str, PipelineResult] = {}
        ranked_lists: list[list[dict[str, Any]]] = []
        names: list[str] = []

        for name, pipeline in self._pipelines.items():
            result = self._retrieve_from_pipeline(
                name, pipeline, optimized_query, username
            )

            # A rewritten query can miss where the literal one hits — notably
            # BM25, which drops every chunk scoring 0.
            if not result.ranked_chunks and not result.error and optimized_query != query:
                logger.info(f"[{name}] empty on optimized query — retrying original.")
                result = self._retrieve_from_pipeline(name, pipeline, query, username)

            per_pipeline[name] = result

            if result.ranked_chunks:
                ranked_lists.append(result.ranked_chunks)
                names.append(name)

        if not ranked_lists:
            logger.warning("All pipelines returned empty results.")
            return PooledResult(
                rrf_ranked_chunks=[],
                rrf_chunk_ids=[],
                per_pipeline=per_pipeline,
                query=query,
                optimized_query=optimized_query,
            )

        rrf_chunks = reciprocal_rank_fusion(ranked_lists, k=self.k, names=names)

        limit = self.top_n if top_n is None else top_n
        if limit is not None:
            rrf_chunks = rrf_chunks[:limit]

        rrf_ids = [c["chunk_id"] for c in rrf_chunks if c.get("chunk_id") is not None]

        logger.info(
            f"CandidatePooler: {len(rrf_chunks)} chunks after RRF "
            f"from {len(ranked_lists)} pipelines."
        )

        return PooledResult(
            rrf_ranked_chunks=rrf_chunks,
            rrf_chunk_ids=rrf_ids,
            per_pipeline=per_pipeline,
            query=query,
            optimized_query=optimized_query,
        )

    def pool_as_ground_truth(
        self,
        query: str,
        username: str | None = None,
        top_n: int | None = None,
    ) -> set[Any]:
        """
        Convenience wrapper: returns just the RRF chunk IDs as a set,
        ready to drop into evaluate_chunks(retrieved_ids, ground_truth_ids).
        """
        return set(self.pool(query=query, username=username, top_n=top_n).rrf_chunk_ids)


def build_default_pooler(
    k: int = DEFAULT_RRF_K,
    top_n: int | None = DEFAULT_TOP_N,
    llm_model: str | None = None,
) -> CandidatePooler:
    """Build a pooler holding exactly one pipeline per retrieval method.

    All pipelines share a single LLM because the LLM affects only query
    rewriting and answer generation, never which chunks are retrieved.
    Returns a pooler with no pipelines when the registry is empty (e.g.
    RAG_DISABLE_ENGINE_INIT is set) — callers should check `pipeline_names`.
    """
    from common.constant import CONFIG_VARIANTS
    from rag.rag_service import rag_registry

    model = llm_model or CONFIG_VARIANTS[0]["model"]
    pooler = CandidatePooler(k=k, top_n=top_n)

    for method in dict.fromkeys(v["method"] for v in CONFIG_VARIANTS):
        try:
            pooler.register(method, rag_registry.get_engine(method, model))
        except Exception as e:
            logger.warning(f"Candidate pooling: skipping '{method}' — {e}")

    return pooler
