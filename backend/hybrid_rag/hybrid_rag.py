from typing import List, Dict, Any
from collections import defaultdict
from rag.base_rag import BaseRAG
from sparse_rag.sparse_rag import SparseRAG
from dense_rag.dense_rag import DenseRAG

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
        self.rrf_k = config.get("rrf_k", 60)
        
        child_config = config.copy()
        child_config["top_k"] = config.get("child_top_k", self.final_top_k * 2)
        
        print(f"Initializing Hybrid Engine (fetching top {child_config['top_k']} from children)...")
        self.sparse_engine = SparseRAG(child_config)
        self.dense_engine = DenseRAG(child_config)

    def index_documents(self, documents: List[str]) -> None:
        """
        Passes the documents to both sub-engines for indexing.
        """
        print("--- Hybrid Indexing ---")
        self.sparse_engine.index_documents(documents)
        self.dense_engine.index_documents(documents)

    def retrieve(self, query: str) -> List[str]:
        """
        1. Get ranked results from Sparse (Keywords).
        2. Get ranked results from Dense (Semantics).
        3. Combine using Reciprocal Rank Fusion (RRF).
        """
        print(f"--- Hybrid Retrieval for: '{query}' ---")
        
        # Parallel retrieval (in a real app, use threading here)
        sparse_results = self.sparse_engine.retrieve(query)
        dense_results = self.dense_engine.retrieve(query)
        
        # Fuse the lists
        fused_results = self._reciprocal_rank_fusion(sparse_results, dense_results)
        
        print(f"Hybrid Fusion selected {len(fused_results)} documents.")
        return fused_results

    def _reciprocal_rank_fusion(self, list_a: List[str], list_b: List[str]) -> List[str]:
        """
        Reciprocal Rank Fusion (RRF) algorithm.
        Score = 1 / (k + rank)
        
        It penalizes documents that appear low in the list, and rewards documents
        that appear in BOTH lists.
        """
        doc_scores = defaultdict(float)

        # 1. Score results from List A (Sparse)
        for rank, doc in enumerate(list_a):
            # rank starts at 0, so we use rank + 1
            score = 1 / (self.rrf_k + rank + 1)
            doc_scores[doc] += score

        # 2. Score results from List B (Dense)
        for rank, doc in enumerate(list_b):
            score = 1 / (self.rrf_k + rank + 1)
            doc_scores[doc] += score

        # 3. Sort by accumulated score (Highest score = Best match)
        sorted_docs = sorted(doc_scores.items(), key=lambda item: item[1], reverse=True)

        # 4. Return the text of the top K results
        return [doc for doc, score in sorted_docs[:self.final_top_k]]