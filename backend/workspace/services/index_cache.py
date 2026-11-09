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


def _key(vector, model):
    return (vector.pk, vector.vectorstore_location, model)


def get_snapshot(engine, vector, model):
    """The snapshot for `vector`, loading it if needed; None if it cannot load."""
    key = _key(vector, model)
    with _lock:
        snapshot = _cache.get(key)
        if snapshot is not None:
            _cache.move_to_end(key)
            return snapshot
    snapshot = _load(engine, vector)
    if snapshot is None:
        return None
    with _lock:
        _cache[key] = snapshot
        _cache.move_to_end(key)
        while len(_cache) > _size():
            _cache.popitem(last=False)
    return snapshot


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


def clear():
    with _lock:
        _cache.clear()
