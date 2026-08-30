import logging
import os
from typing import List, Dict, Any, Optional
from collections import defaultdict
import numpy as np
from rag.base_rag import BaseRAG
from sparse_rag.sparse_rag import SparseRAG
from dense_rag.dense_rag import DenseRAG

try:
    from sentence_transformers import CrossEncoder
except ImportError:
    CrossEncoder = None

logger = logging.getLogger(__name__)


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
            logger.error(f"Ollama nomic-embed-text reranker error: {e}")
            return np.zeros(len(pairs), dtype=np.float32)


class HybridRAG(BaseRAG):
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes Hybrid RAG by creating both Sparse and Dense sub-engines.

        Config arguments:
        - top_k: (int) Final number of documents to return.
        - rrf_k: (int) The constant 'k' for RRF algorithm (default 60).
        - child_top_k: (int) How many docs to fetch from sub-engines before fusion.
                       Usually higher than top_k (e.g., fetch 10 from each to find the best 3).
        - reranker_model: (str) Model name for reranking (default "nomic-embed-text" via Ollama).
        - ollama_embed_model: (str) Ollama model for embedding reranking (default "nomic-embed-text").
        - device: (str) Device to use for PyTorch models ("auto", "cuda", or "cpu").
        """
        super().__init__(config)

        self.final_top_k = config.get("top_k", 3)
        self.child_top_k = config.get("child_top_k", 10)
        self.rrf_k = config.get("rrf_k", 60)
        self.reranker_model = config.get("reranker_model", "nomic-embed-text")
        self.ollama_embed_model = config.get("ollama_embed_model", "nomic-embed-text")

        # Determine device
        device = config.get("device", "auto")
        if not device or str(device).lower() == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"
        self.device = str(device).lower()

        print(f"Initializing Hybrid Engine (fetching top {self.child_top_k} from children)...")
        self.sparse_engine = SparseRAG(config)
        self.dense_engine = DenseRAG(config)

        is_ollama_model = (
            self.reranker_model.startswith("ollama")
            or self.reranker_model in ("nomic-embed-text", "ollama")
            or "nomic" in self.reranker_model
            or config.get("reranker_type") == "ollama"
        )

        if is_ollama_model or CrossEncoder is None:
            embed_model = (
                self.reranker_model.replace("ollama/", "")
                if self.reranker_model.startswith("ollama/")
                else self.ollama_embed_model
            )
            logger.info(f"Using Ollama ({embed_model}) for cross-encoder reranking (GPU/CPU managed by Ollama).")
            self._cross_encoder = OllamaCrossEncoder(model_name=embed_model)
        else:
            try:
                logger.info(f"Using CrossEncoder ({self.reranker_model}) on device: {self.device}")
                self._cross_encoder = CrossEncoder(self.reranker_model, device=self.device)
            except Exception as e:
                logger.warning(
                    f"Failed to initialize CrossEncoder ({self.reranker_model}) on {self.device} ({e}), "
                    f"falling back to Ollama {self.ollama_embed_model}"
                )
                self._cross_encoder = OllamaCrossEncoder(model_name=self.ollama_embed_model)

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