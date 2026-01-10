import torch
from typing import List, Dict, Any, Union
from sentence_transformers import CrossEncoder

class Reranker:
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the Cross-Encoder Reranker.
        
        Config arguments:
        - model: (str) HuggingFace model path. 
                 Default: 'cross-encoder/ms-marco-MiniLM-L-6-v2' (Fast & Good)
                 Better/Slower: 'BAAI/bge-reranker-base'
        - top_k: (int) Default number of chunks to return after ranking.
        - device: (str) 'cpu' or 'cuda'. Auto-detected if not provided.
        """
        self.model_name = config.get("model", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        self.default_top_k = config.get("top_k", 3)
        
        # Auto-detect device if not specified
        if "device" in config:
            self.device = config["device"]
        else:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"

        print(f"Loading Reranker Model: {self.model_name} on {self.device}...")
        self.model = CrossEncoder(self.model_name, device=self.device)

    def rank(self, query: str, documents: List[str], top_k: int = 3) -> List[str]:
        """
        Takes a query and a list of documents, scores them by relevance,
        and returns the top_k most relevant chunks.
        """
        if not documents:
            return []

        # Override default top_k if provided
        final_top_k = top_k if top_k is not None else self.default_top_k

        # 1. Prepare Pairs: Cross-Encoders expect input as [[Query, Doc1], [Query, Doc2], ...]
        model_inputs = [[query, doc] for doc in documents]

        # 2. Predict Scores (This is the slow part)
        # Returns a list of floats (e.g., [0.9, 0.1, 0.5])
        scores = self.model.predict(model_inputs)

        # 3. Combine Documents with their Scores
        scored_docs = list(zip(documents, scores))

        # 4. Sort by Score (Descending order - highest relevance first)
        scored_docs = sorted(scored_docs, key=lambda x: x[1], reverse=True)

        # Debug print to show how re-ranking changed things
        print(f"\n--- Reranking Top {len(documents)} Candidates ---")
        for i, (doc, score) in enumerate(scored_docs[:final_top_k]):
            print(f"Rank {i+1} (Score: {score:.4f}): {doc[:50]}...")

        # 5. Extract just the text for the Top K
        final_results = [doc for doc, score in scored_docs[:final_top_k]]

        return final_results