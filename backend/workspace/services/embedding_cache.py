"""Persistent per-document embedding checkpoint (PRD §41).

The ingestion worker embeds chunk texts batch by batch and commits each batch
here before starting the next, so a failure at chunk 700 of 1,000 loses one
batch at most and a retry embeds only what is missing. `_build_index` then
reads the vectors back through `EmbeddingCache.lookup` instead of calling the
provider, which keeps its single atomic transaction short.

Keyed by (document, embedding model, sha256 of the exact chunk text): a new
embedding model or a re-chunked text simply misses.
"""
import hashlib

import numpy as np
from django.db import transaction

from workspace.models import EmbeddingCacheEntry

# Stays well below SQLite's bound-parameter limit for `text_hash__in`.
LOOKUP_BATCH = 500


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def encode_vector(vector) -> bytes:
    return np.asarray(vector, dtype="<f4").tobytes()


def decode_vector(blob, dimensions) -> np.ndarray:
    values = np.frombuffer(bytes(blob), dtype="<f4")
    if values.shape[0] != dimensions:
        raise ValueError("Stored embedding has the wrong length")
    return values.astype(np.float64)


class EmbeddingCache:
    def __init__(self, document_id, model):
        self.document_id = document_id
        self.model = model

    def lookup(self, texts):
        """{text: vector} for every given text that has a committed embedding."""
        by_hash = {text_hash(text): text for text in dict.fromkeys(texts)}
        hashes = list(by_hash)
        found = {}
        for start in range(0, len(hashes), LOOKUP_BATCH):
            rows = EmbeddingCacheEntry.objects.filter(
                document_id=self.document_id, model=self.model,
                text_hash__in=hashes[start:start + LOOKUP_BATCH],
            ).values_list("text_hash", "dimensions", "vector")
            for digest, dimensions, blob in rows:
                try:
                    found[by_hash[digest]] = decode_vector(blob, dimensions)
                except ValueError:
                    continue  # A damaged row is treated as missing and re-embedded.
        return found

    def missing(self, texts):
        """Unique texts, in first-seen order, that still need an embedding."""
        cached = self.lookup(texts)
        return [text for text in dict.fromkeys(texts) if text not in cached]

    def store(self, texts, vectors):
        """Commit one batch. Safe to repeat: existing rows are left alone."""
        entries = [
            EmbeddingCacheEntry(
                document_id=self.document_id, model=self.model, text_hash=text_hash(text),
                dimensions=len(vector), vector=encode_vector(vector),
            )
            for text, vector in zip(texts, vectors)
        ]
        with transaction.atomic():
            EmbeddingCacheEntry.objects.bulk_create(entries, ignore_conflicts=True)
