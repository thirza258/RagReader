from typing import List, Dict, Any
from collections import defaultdict
from rag.base_rag import BaseRAG
from sparse_rag.sparse_rag import SparseRAG
from dense_rag.dense_rag import DenseRAG
import torch
import numpy as np
from sentence_transformers import CrossEncoder
from transformers import AutoModelForSequenceClassification, AutoTokenizer, AutoModel

import logging

logger = logging.getLogger(__name__)

_CROSS_ENCODER = "cross_encoder"
_QWEN3         = "qwen3"
_JINA          = "jina"

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
        self.reranker_model = config.get( "reranker_model", "cross-encoder/ms-marco-MiniLM-L6-v2")
        
        print(f"Initializing Hybrid Engine (fetching top {self.child_top_k} from children)...")
        self.sparse_engine = SparseRAG(config)
        self.dense_engine = DenseRAG(config)
        
        self._strategy = self._determine_reranker_strategy(self.reranker_model)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._load_reranker()
        
        self.document_metadata = []  
        
    def _determine_reranker_strategy(self, model_name: str) -> str:
        if "cross-encoder" in model_name:
            return _CROSS_ENCODER
        elif "qwen3-reranker" in model_name:
            return _QWEN3
        elif "jina-reranker" in model_name:
            return _JINA
        else:
            raise ValueError(f"Unsupported reranker model: {model_name!r}")
        
    def _load_reranker(self) -> None:
        if self._strategy == _CROSS_ENCODER:
            self._load_cross_encoder()
        elif self._strategy == _QWEN3:
            self._load_qwen3()
        elif self._strategy == _JINA:
            self._load_jina()
        else:
            raise ValueError(f"Unknown reranker strategy: {self._strategy!r}")

    def _load_cross_encoder(self) -> None:
        self._cross_encoder = CrossEncoder(self.reranker_model)

    def _load_qwen3(self) -> None:
        
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.reranker_model, trust_remote_code=True, padding_side="left"
        )
        self._model = (
            AutoModelForSequenceClassification.from_pretrained(self.reranker_model, trust_remote_code=True).to(self.device)
        )
        self._model.eval()

    def _load_jina(self) -> None:
        self._model = (
            AutoModel.from_pretrained(
                self.reranker_model,
                dtype="auto",
                trust_remote_code=True,
            ).to(self.device)
        )
        self._model.eval()

    def index_documents(self, documents: List[str]) -> None:
        self.sparse_engine.index_documents(documents)
        self.dense_engine.index_documents(documents)
        self._documents = documents
        self.document_metadata = [{"chunk_id": doc.get("chunk_id")} for doc in documents]

    def retrieve(self, query: str) -> List[str]:
        """
        1. Get ranked results from Sparse (Keywords).
        2. Get ranked results from Dense (Semantics).
        3. Combine using Reciprocal Rank Fusion (RRF).
        """
        print(f"--- Hybrid Retrieval for: '{query}' ---")
        
        sparse_results = self.sparse_engine.retrieve(query)
        dense_results = self.dense_engine.retrieve(query)
        
        logger.debug(f"Sparse docs: {len(self.sparse_engine.documents)}, "
                 f"Dense docs: {len(self.dense_engine.documents)}")

        seen: set = set()
        candidates: List[str] = []
        for r in sparse_results + dense_results:
            text = r["text"].strip()
            if text not in seen:
                seen.add(text)
                candidates.append(text)
        
        reranked = self._rerank(query, candidates)
        return reranked[:self.final_top_k]

    def _rerank(self, query, candidates: List[str]) -> List[str]:
        try:
            if self._strategy == _CROSS_ENCODER:
                return self._rerank_cross_encoder(query, candidates)
            elif self._strategy == _QWEN3:
                return self._rerank_qwen3(query, candidates)
            elif self._strategy == _JINA:
                return self._rerank_jina(query, candidates)
            else:
                logger.warning(f"Unknown reranking strategy: {self._strategy!r}. Returning unranked candidates.")
                return candidates
        except Exception as exc:
             logger.error(f"Reranking error ({self._strategy}): {exc}")
             return candidates
        
    def _rerank_cross_encoder(
        self, query: str, candidates: List[str]
    ) -> List[str]:
        """sentence-transformers CrossEncoder — handles batching internally."""
        pairs  = [(query, doc) for doc in candidates]
        scores = self._cross_encoder.predict(pairs)           # np.ndarray
        ranked = np.argsort(scores)[::-1]
        return [candidates[i] for i in ranked]

    def _rerank_qwen3(
        self, query: str, candidates: List[str], batch_size: int = 8
    ) -> List[str]:
        """
        Qwen3-Reranker uses a causal LM head; the reranking score is read from
        the logits of the 'yes' / 'no' token at the final position.

        The official prompt template wraps the pair in an instruction so the
        model outputs a relevance judgement.
        """
        _PROMPT = (
            "<|im_start|>system\nJudge whether the document is relevant "
            "to the query. Reply with 'yes' or 'no'.<|im_end|>\n"
            "<|im_start|>user\nQuery: {query}\nDocument: {doc}<|im_end|>\n"
            "<|im_start|>assistant\n"
        )

        yes_id = self._tokenizer.convert_tokens_to_ids("yes")
        no_id  = self._tokenizer.convert_tokens_to_ids("no")

        scores: List[float] = []

        with torch.no_grad():
            for i in range(0, len(candidates), batch_size):
                batch = candidates[i : i + batch_size]
                texts = [_PROMPT.format(query=query, doc=d) for d in batch]

                inputs = self._tokenizer(
                    texts,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt",
                ).to(self.device)

                logits = self._model(**inputs).logits  

                last_logits = logits[:, -1, :]                      
                yn_logits   = last_logits[:, [yes_id, no_id]]       
                probs       = torch.softmax(yn_logits, dim=-1)[:, 0] 
                scores.extend(probs.cpu().tolist())

        ranked = np.argsort(scores)[::-1]
        return [candidates[i] for i in ranked]

    def _rerank_jina(
        self, query: str, candidates: List[str]
    ) -> List[str]:
        """
        jina-reranker-v3 exposes a high-level .rerank() method that returns
        results pre-sorted by score descending.
        """
        results = self._model.rerank(
            query,
            candidates,
            max_query_length=512,
            max_length=1024,
            top_n=len(candidates),   
        )
        return [r["document"]["text"] for r in results]
    
    def get_retrieved_scores(self, query: str) -> Dict[str, Any]:
        """
        Returns the RRF scores for all documents given a query.
        Useful for evaluation purposes.
        """
        sparse_results = self.sparse_engine.retrieve(query)
        dense_results = self.dense_engine.retrieve(query)
        
        doc_scores = defaultdict(float)

        for rank, doc in enumerate(sparse_results):
            score = 1 / (self.rrf_k + rank + 1)
            doc_scores[doc] += score

        for rank, doc in enumerate(dense_results):
            score = 1 / (self.rrf_k + rank + 1)
            doc_scores[doc] += score

        return {"scores": dict(doc_scores)}