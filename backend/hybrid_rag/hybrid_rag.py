import logging
import os
from typing import List, Dict, Any, Optional
from collections import defaultdict
import numpy as np
from rag.base_rag import BaseRAG
from sparse_rag.sparse_rag import SparseRAG
from dense_rag.dense_rag import DenseRAG

from common.constant import (
    DEFAULT_CHILD_TOP_K,
    DEFAULT_OLLAMA_EMBED_MODEL,
    DEFAULT_RERANKER_MODEL,
    DEFAULT_RRF_K,
)

logger = logging.getLogger(__name__)


class RerankUnavailable(RuntimeError):
    """Ollama could not score the candidates.

    Raised rather than returning a neutral score array: uniform scores are
    indistinguishable from a genuine result, so the caller would rank on them
    and report retrieval metrics for a rerank that never happened.
    """


class OllamaCrossEncoder:
    """Reranker using Ollama nomic-embed-text embeddings (GPU/CPU managed by Ollama)."""

    def __init__(self, model_name: str = "nomic-embed-text", host: Optional[str] = None, *args, **kwargs):
        self.model_name = model_name
        self.host = host or os.getenv("OLLAMA_HOST")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import ollama
            self._client = ollama.Client(host=self.host) if self.host else ollama.Client()
        return self._client

    def predict(self, pairs: List[tuple[str, str] | List[str]]) -> np.ndarray:
        """
        Calculates cosine similarity scores between query and document pairs using Ollama embeddings.
        pairs: list of (query, doc_text) tuples
        Returns: np.ndarray of float scores
        """
        if not pairs:
            return np.array([], dtype=np.float32)

        try:
            queries = [p[0] for p in pairs]
            docs = [p[1] for p in pairs]

            unique_queries = list(dict.fromkeys(queries))
            query_embs = {}
            for q in unique_queries:
                res = self.client.embed(model=self.model_name, input=f"search_query: {q}")
                query_embs[q] = np.array(res["embeddings"][0], dtype=np.float32)

            doc_inputs = [f"search_document: {d}" for d in docs]
            res_docs = self.client.embed(model=self.model_name, input=doc_inputs)
            doc_embs = np.array(res_docs["embeddings"], dtype=np.float32)

            scores = []
            for i, (q, _) in enumerate(pairs):
                q_vec = query_embs[q]
                d_vec = doc_embs[i]
                norm_q = np.linalg.norm(q_vec)
                norm_d = np.linalg.norm(d_vec)
                if norm_q > 0 and norm_d > 0:
                    sim = float(np.dot(q_vec, d_vec) / (norm_q * norm_d))
                else:
                    sim = 0.0
                scores.append(sim)

            return np.array(scores, dtype=np.float32)
        except Exception as e:
            raise RerankUnavailable(
                f"Ollama reranker '{self.model_name}' failed: {e}. "
                f"Is Ollama reachable, and has the model been pulled "
                f"(`ollama pull {self.model_name}`)?"
            ) from e


# Reranking runs through Ollama, which holds the model and decides GPU vs CPU
# for itself. Pipelines are built per (method, model, config), so several
# hybrid engines can be alive at once; caching the client keyed by model name
# keeps them from each opening their own.
_CROSS_ENCODER_CACHE: Dict[str, Any] = {}


def build_cross_encoder(model_name: str = DEFAULT_OLLAMA_EMBED_MODEL):
    """Construct the reranker for `model_name`.

    An `ollama/` prefix is accepted and stripped, so a config written as
    `ollama/nomic-embed-text` and one written as `nomic-embed-text` name the
    same model.
    """
    embed_model = model_name.replace("ollama/", "", 1) if model_name.startswith("ollama/") else model_name
    logger.info(f"Using Ollama ({embed_model}) for reranking.")
    return OllamaCrossEncoder(model_name=embed_model)


def get_cross_encoder(model_name: str = DEFAULT_OLLAMA_EMBED_MODEL):
    """Return the shared reranker for `model_name`, building it once."""
    encoder = _CROSS_ENCODER_CACHE.get(model_name)
    if encoder is None:
        encoder = build_cross_encoder(model_name)
        _CROSS_ENCODER_CACHE[model_name] = encoder
    return encoder


def clear_cross_encoder_cache() -> None:
    """Drop every cached reranker. For tests and for freeing memory."""
    _CROSS_ENCODER_CACHE.clear()


class HybridRAG(BaseRAG):
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes Hybrid RAG by creating both Sparse and Dense sub-engines.

        Config arguments:
        - top_k: (int) Final number of documents to return.
        - rrf_k: (int) The constant 'k' for RRF algorithm (default 60).
        - child_top_k: (int) How many docs to fetch from sub-engines before fusion.
                       Usually higher than top_k (e.g., fetch 10 from each to find the best 3).
        - reranker_model: (str) Ollama model that reranks the fused candidates.
                       Chosen from common.constant.RERANKER_MODELS — unlike a
                       generation model this one is served by a local Ollama,
                       so the set is closed rather than open.
        """
        super().__init__(config)

        self.final_top_k = config.get("top_k", 3)
        self.child_top_k = config.get("child_top_k", DEFAULT_CHILD_TOP_K)
        self.rrf_k = config.get("rrf_k", DEFAULT_RRF_K)
        self.reranker_model = config.get("reranker_model", DEFAULT_RERANKER_MODEL)

        print(f"Initializing Hybrid Engine (fetching top {self.child_top_k} from children)...")
        # The sub-engines build the candidate pool the cross-encoder reranks, so
        # they must fetch `child_top_k` — not the config's `top_k`, which is the
        # *final* cut. Passing `config` straight through would leave a reranker
        # with exactly as many candidates as it is asked to return.
        child_config = {**config, "top_k": self.child_top_k}
        self.sparse_engine = SparseRAG(child_config)
        self.dense_engine = DenseRAG(child_config)

        self._cross_encoder = get_cross_encoder(self.reranker_model)

        self.document_metadata = []

    def index_documents(self, documents: List[str]) -> None:
        self.sparse_engine.index_documents(documents)
        self.dense_engine.index_documents(documents)
        self._documents = documents
        self.document_metadata = [{"chunk_id": doc.get("chunk_id")} for doc in documents]

    def retrieve(self, query: str) -> List[str]:
        """
        1. Get ranked results from Sparse (Keywords).
        2. Get ranked results from Dense (Semantics).
        3. Deduplicate candidates.
        4. Rerank with CrossEncoder and return top_k.
        """
        print(f"--- Hybrid Retrieval for: '{query}' ---")

        sparse_results = self.sparse_engine.retrieve(query)
        dense_results = self.dense_engine.retrieve(query)

        seen: set = set()
        candidates: List[Dict[str, Any]] = []
        for r in sparse_results + dense_results:
            text = r["text"].strip()
            if text not in seen:
                seen.add(text)
                candidates.append(r)

        reranked = self._rerank(query, candidates)
        return reranked[: self.final_top_k]

    def _rerank(self, query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Rerank candidate chunk dicts with the cross-encoder.

        Keeps the {text, chunk_id, score} contract shared by all engines —
        `score` is replaced with the cross-encoder relevance score.
        """
        if not candidates:
            return []
        try:
            pairs = [(query, doc["text"]) for doc in candidates]
            scores = self._cross_encoder.predict(pairs)
            # Descending, and stable so equal scores keep the fused order they
            # arrived in. `argsort(scores)[::-1]` would reverse ties instead.
            ranked = np.argsort(-np.asarray(scores), kind="stable")
            return [
                {**candidates[i], "score": float(scores[i])}
                for i in ranked
            ]
        except Exception as exc:
            # Fall back to the fused RRF order. It is the best ranking we have
            # without the reranker, and it beats ranking on scores we could not
            # actually compute.
            logger.error(
                f"Reranking failed, keeping fused RRF order for {len(candidates)} "
                f"candidates: {exc}"
            )
            return candidates

    def get_retrieved_scores(self, query: str) -> Dict[str, Any]:
        """
        Returns the RRF scores for all documents given a query.
        Useful for evaluation purposes.
        """
        sparse_results = self.sparse_engine.retrieve(query)
        dense_results = self.dense_engine.retrieve(query)

        doc_scores = defaultdict(float)

        for rank, doc in enumerate(sparse_results):
            doc_scores[doc["text"]] += 1 / (self.rrf_k + rank + 1)

        for rank, doc in enumerate(dense_results):
            doc_scores[doc["text"]] += 1 / (self.rrf_k + rank + 1)

        return {"scores": dict(doc_scores)}