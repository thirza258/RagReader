"""Pipeline construction and lookup.

Engines used to be built eagerly: one instance per (method × model) at import
time, nine in all. That only works while the model list is closed. Now that any
OpenRouter model can be selected the matrix is unbounded, so engines are built
on first use and held in a bounded LRU cache.

The cache key is (method, model, config fingerprint) rather than just
(method, model). Two runs that differ only in reranker, embedding model or
temperature need different engines; keying on the pair alone would hand the
second run the first one's settings and report the result as if it had been
configured as asked.

Retrieval *depth* is deliberately not part of that key. It is cheap to change
on a live engine, and `apply_retrieval_depth` sets it before every call.
"""
import hashlib
import json
import logging
import os
from collections import OrderedDict
from typing import Any, Dict, Optional

from pipeline.dense_rag_pipeline import DenseRAGPipeline
from pipeline.hybrid_rag_pipeline import HybridRAGPipeline
from pipeline.sparse_rag_pipeline import SparseRAGPipeline

from common.constant import (
    DEFAULT_CHILD_TOP_K,
    DEFAULT_TOP_K,
    PIPELINE_SHAPING_KEYS,
    build_pipeline_config,
    is_valid_model_id,
)

logger = logging.getLogger(__name__)

# Retrieval methods stay a closed set: each one needs a pipeline class.
PIPELINE_CLASSES = {
    "Dense Retrieval": DenseRAGPipeline,
    "Sparse Retrieval": SparseRAGPipeline,
    "Hybrid Retrieval": HybridRAGPipeline,
}

# How many built engines to keep. Each hybrid engine holds two sub-engines and
# a reference to a (shared) cross-encoder, so this is the ceiling on how much
# model-switching costs in memory.
DEFAULT_ENGINE_CACHE_SIZE = 12


def engine_init_disabled() -> bool:
    """True when this process must not construct pipelines.

    The test suite sets it: constructing a pipeline reaches for an API key and,
    for hybrid, downloads a cross-encoder. With the flag set a cache miss is an
    error rather than a silent network call.
    """
    return os.getenv("RAG_DISABLE_ENGINE_INIT", "").lower() in ("1", "true")


def _cache_size() -> int:
    try:
        return max(1, int(os.getenv("RAG_ENGINE_CACHE_SIZE", DEFAULT_ENGINE_CACHE_SIZE)))
    except (TypeError, ValueError):
        return DEFAULT_ENGINE_CACHE_SIZE


def config_fingerprint(pipeline_config: Dict[str, Any]) -> str:
    """A short, stable digest of everything that changes how an engine is built."""
    shaped = {key: pipeline_config.get(key) for key in PIPELINE_SHAPING_KEYS}
    encoded = json.dumps(shaped, sort_keys=True, default=str).encode()
    return hashlib.md5(encoded).hexdigest()[:12]


def apply_retrieval_depth(
    engine,
    top_k: int = DEFAULT_TOP_K,
    child_top_k: Optional[int] = None,
) -> None:
    """Set how many chunks `engine` returns, for this run.

    Engines are shared between runs, so call this before *every* variant rather
    than only when the depth changes — otherwise one run's Top-K leaks into the
    next. Derived values are computed from the arguments alone, never from the
    engine's current state, so repeated calls can't drift.

    `child_top_k` is the configured floor for Hybrid's candidate pool. The pool
    still widens with `top_k` when that would otherwise leave the reranker with
    exactly as many candidates as it must return.
    """
    rag = getattr(engine, "rag", None)
    if rag is None:
        return

    dense = getattr(rag, "dense_engine", None)
    sparse = getattr(rag, "sparse_engine", None)

    if dense is not None or sparse is not None:
        # Hybrid: the sub-engines build the candidate pool, the reranker trims
        # it to top_k. The pool has to be at least as deep as the final cut.
        floor = child_top_k if child_top_k else DEFAULT_CHILD_TOP_K
        child_depth = max(top_k * 2, floor)
        rag.final_top_k = top_k
        rag.child_top_k = child_depth
        for child in (dense, sparse):
            if child is not None:
                child.top_k = child_depth
        return

    if hasattr(rag, "top_k"):
        rag.top_k = top_k


class RAGRegistry:
    """Builds pipelines on demand and keeps the most recent ones around."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # Insertion-ordered so the oldest entry is the one evicted.
        self.engines: "OrderedDict[tuple, Any]" = OrderedDict()
        self.max_size = _cache_size()
        self._initialized = True

    def get_engine(self, method: str, llm_model: str, config: Optional[dict] = None):
        """Return the pipeline for this method, model and run configuration.

        Usage: registry.get_engine("Dense Retrieval", "openai/gpt-4o-mini")

        `config` is a normalized analysis config; omitting it uses the defaults,
        which is what the plain chat path wants.
        """
        if method not in PIPELINE_CLASSES:
            raise ValueError(
                f"Unknown retrieval method '{method}'. "
                f"Available: {sorted(PIPELINE_CLASSES)}"
            )

        if not is_valid_model_id(llm_model):
            raise ValueError(
                f"'{llm_model}' is not a valid OpenRouter model id — "
                "expected the form 'provider/model'."
            )

        pipeline_config = build_pipeline_config(config, llm_model)
        key = (method, llm_model, config_fingerprint(pipeline_config))

        engine = self.engines.get(key)
        if engine is not None:
            self.engines.move_to_end(key)
            return engine

        if engine_init_disabled():
            raise RuntimeError(
                "RAG_DISABLE_ENGINE_INIT is set, so no engine can be built for "
                f"'{method}' / '{llm_model}'."
            )

        logger.info(f"Building {method} pipeline for {llm_model}...")
        engine = PIPELINE_CLASSES[method](pipeline_config)

        self.engines[key] = engine
        self._evict_to_size()
        return engine

    def _evict_to_size(self) -> None:
        while len(self.engines) > self.max_size:
            evicted, _ = self.engines.popitem(last=False)
            logger.info(f"Evicting cached engine {evicted[0]} / {evicted[1]}")

    def clear(self) -> None:
        """Drop every cached engine."""
        self.engines.clear()


# Create a global instance
rag_registry = RAGRegistry()
