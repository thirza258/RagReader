from typing import List, Dict, Any
from collections import defaultdict
from rag.base_rag import BaseRAG
from sparse_rag.sparse_rag import SparseRAG
from dense_rag.dense_rag import DenseRAG
import numpy as np
from sentence_transformers import CrossEncoder

import logging

logger = logging.getLogger(__name__)


class HybridRAG(BaseRAG):
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes Hybrid RAG by creating both Sparse and Dense sub-engines.

        Config arguments:
        - top_k: (int) Final number of documents to return.
        - rrf_k: (int) The constant 'k' for RRF algorithm (default 60).
        - child_top_k: (int) How many docs to fetch from sub-engines before fusion.
                       Usually higher than top_k (e.g., fetch 10 from each to find the best 3).
        """
        super().__init__(config)

        self.final_top_k = config.get("top_k", 3)
        self.child_top_k = config.get("child_top_k", 10)
        self.rrf_k = config.get("rrf_k", 60)
        self.reranker_model = config.get("reranker_model", "cross-encoder/ms-marco-MiniLM-L6-v2")

        print(f"Initializing Hybrid Engine (fetching top {self.child_top_k} from children)...")
        self.sparse_engine = SparseRAG(config)
        self.dense_engine = DenseRAG(config)

        self._cross_encoder = CrossEncoder(self.reranker_model)

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
            ranked = np.argsort(scores)[::-1]
            return [
                {**candidates[i], "score": float(scores[i])}
                for i in ranked
            ]
        except Exception as exc:
            logger.error(f"Reranking error: {exc}")
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