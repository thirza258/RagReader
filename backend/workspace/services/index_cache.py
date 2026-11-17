"""Loaded dense indexes for chat, kept per process in a small LRU.

A chat question can span several documents, and the shared engine holds only
one document's index at a time. So each index is loaded through the engine's
own `_load_state` (which validates the embedding-model stamp and chunk
config), copied out as an immutable float32 snapshot, and the engine is put
back exactly as it was. Retrieval then scores snapshots without touching the
engine, and repeat questions skip unpickling entirely.

Keyed by DocumentVector id (plus location and model, so a reused id or a
changed model can never return a stale snapshot). A re-index creates a new
DocumentVector, so it is a new key; deleted documents are evicted explicitly.

BM25 (Phase 3) is built over the *union* of the in-scope snapshots' passages,
so its scores are comparable across documents (one IDF, one average length).
Building it tokenizes every passage, so the built index is cached too, keyed
by the set of index versions it covers; `discard` and `clear` drop both kinds.
"""
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
from django.conf import settings

from rag.rag_service import engine_execution

logger = logging.getLogger(__name__)

_cache: "OrderedDict[tuple, IndexSnapshot]" = OrderedDict()
_lock = threading.Lock()
_bm25_cache: "OrderedDict[frozenset, Bm25Index]" = OrderedDict()
_bm25_lock = threading.Lock()


@dataclass(frozen=True)
class IndexSnapshot:
    vector_id: int
    texts: tuple
    chunk_ids: tuple
    matrix: np.ndarray  # float32, rows L2-normalised, read-only

    @property
    def dimensions(self):
        return self.matrix.shape[1] if self.matrix.ndim == 2 else 0

    def __len__(self):
        return len(self.texts)


def _size():
    return max(1, int(getattr(settings, "RAG_CHAT_INDEX_CACHE_SIZE", 8) or 8))


def _bm25_size():
    return max(1, int(getattr(settings, "RAG_CHAT_BM25_CACHE_SIZE", 4) or 4))


def _key(vector, model):
    return (vector.pk, vector.vectorstore_location, model)


def get_snapshot(engine, vector, model):
    """The snapshot for `vector`, loading it if needed; None if it cannot load."""
    return fetch_snapshot(engine, vector, model)[0]


def fetch_snapshot(engine, vector, model):
    """(snapshot or None, cache hit) — the hit flag is for the request trace."""
    key = _key(vector, model)
    with _lock:
        snapshot = _cache.get(key)
        if snapshot is not None:
            _cache.move_to_end(key)
            return snapshot, True
    snapshot = _load(engine, vector)
    if snapshot is None:
        return None, False
    with _lock:
        _cache[key] = snapshot
        _cache.move_to_end(key)
        while len(_cache) > _size():
            _cache.popitem(last=False)
    return snapshot, False


def _load(engine, vector):
    with engine_execution(engine):
        rag = engine.rag
        # _load_state rebinds attributes on engine.rag (dense) or swaps its
        # sub-engines (hybrid); restoring the attribute dict undoes either, so
        # a chat lookup never changes what a concurrent legacy run sees.
        saved = dict(rag.__dict__)
        try:
            if not engine._load_state(vector.vectorstore_location):
                return None
            dense = getattr(engine.rag, "dense_engine", engine.rag)
            texts = tuple(dense.documents or ())
            chunk_ids = tuple((meta or {}).get("chunk_id") for meta in (dense.document_metadata or ()))
            vectors = np.array(dense.document_vectors, dtype=np.float32, copy=True)
        except Exception:
            logger.warning("Index %s could not be loaded for chat", vector.pk, exc_info=True)
            return None
        finally:
            rag.__dict__.clear()
            rag.__dict__.update(saved)
    if vectors.ndim != 2 or len(texts) != vectors.shape[0] or len(chunk_ids) != len(texts):
        return None
    if len(texts):
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors = vectors / norms
    vectors.setflags(write=False)
    return IndexSnapshot(vector_id=vector.pk, texts=texts, chunk_ids=chunk_ids, matrix=vectors)


def discard(vector_ids):
    ids = set(vector_ids)
    with _lock:
        for key in [key for key in _cache if key[0] in ids]:
            del _cache[key]
    with _bm25_lock:
        for key in [key for key in _bm25_cache if any(vector_id in ids for vector_id, _location in key)]:
            del _bm25_cache[key]


def clear():
    with _lock:
        _cache.clear()
    with _bm25_lock:
        _bm25_cache.clear()


# ── BM25 over the union of loaded snapshots ──────────────────────────────────

class Bm25Index:
    """BM25Okapi over the passages of several snapshots, in index-version order.

    `offsets[vector_id]` is where that snapshot's passages start in the
    corpus, so `scores()` can hand each caller its own slice whatever order
    it loaded the documents in.
    """

    def __init__(self, snapshots):
        from rank_bm25 import BM25Okapi
        from sparse_rag.sparse_rag import english_stop_words, tokenize

        self.stop_words = frozenset(english_stop_words())
        self.offsets, corpus = {}, []
        for snapshot in sorted(snapshots, key=lambda item: item.vector_id):
            self.offsets[snapshot.vector_id] = len(corpus)
            corpus.extend(tokenize(text, self.stop_words) for text in snapshot.texts)
        self.size = len(corpus)
        self.tokens = sum(len(tokens) for tokens in corpus)
        # BM25Okapi divides by the average passage length: a corpus without a
        # single token (or without passages) scores everything 0 instead.
        self._bm25 = BM25Okapi(corpus) if self.size and self.tokens else None

    def query_tokens(self, query):
        from sparse_rag.sparse_rag import tokenize
        return tokenize(query, self.stop_words)

    def scores(self, query, snapshots):
        """{vector_id: float64 scores of that snapshot's passages}."""
        tokens = self.query_tokens(query)
        if self._bm25 is None or not tokens:
            return {snapshot.vector_id: np.zeros(len(snapshot), dtype=np.float64) for snapshot in snapshots}
        everything = np.asarray(self._bm25.get_scores(tokens), dtype=np.float64)
        return {
            snapshot.vector_id: everything[self.offsets[snapshot.vector_id]:self.offsets[snapshot.vector_id] + len(snapshot)]
            for snapshot in snapshots
        }


def _bm25_key(snapshots, locations):
    return frozenset((snapshot.vector_id, locations.get(snapshot.vector_id, "")) for snapshot in snapshots)


def fetch_bm25(snapshots, locations=None):
    """(Bm25Index over `snapshots`, cache hit). Keyed by the set of index versions."""
    key = _bm25_key(snapshots, locations or {})
    with _bm25_lock:
        index = _bm25_cache.get(key)
        if index is not None:
            _bm25_cache.move_to_end(key)
            return index, True
    index = Bm25Index(snapshots)
    with _bm25_lock:
        _bm25_cache[key] = index
        _bm25_cache.move_to_end(key)
        while len(_bm25_cache) > _bm25_size():
            _bm25_cache.popitem(last=False)
    return index, False
