import numpy as np
from typing import List, Dict, Any, Optional
from django.conf import settings
from openai import OpenAI
from sklearn.metrics.pairwise import cosine_similarity
from rag.base_rag import BaseRAG
from common.constant import DEFAULT_EMBEDDING_MODEL
from common.embeddings import embed_texts, validate_vectors, EMBEDDING_TIMEOUT_SECONDS
from common.errors import PipelineError

class DenseRAG(BaseRAG):
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the DenseRAG engine using OpenRouter.
        
        Config arguments:
        - top_k: (int) Number of chunks to retrieve.
        - embedding_model: (str) OpenRouter embedding model
                 (e.g., "openai/text-embedding-3-small", "qwen/qwen3-embedding-8b").
                 Also accepted as "model", the engine's original spelling.
        """
        super().__init__(config)
        
        api_key = settings.OPENROUTER_API_KEY
        if not api_key:
            raise PipelineError("missing_provider_key", "OpenRouter API key is not configured. Set OPENROUTER_API_KEY before indexing.", http_status=503)
        
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            timeout=EMBEDDING_TIMEOUT_SECONDS,
            max_retries=1,
        )
        
        self.top_k = config.get("top_k", 3)
        # "embedding_model" is the clear spelling; "model" is what this engine
        # has always read and is still honoured so older configs keep working.
        self.model = (
            config.get("embedding_model")
            or config.get("model")
            or DEFAULT_EMBEDDING_MODEL
        )
        
        self.documents: List[str] =[]  
        self.document_vectors: Optional[np.ndarray] = None 
        self.document_metadata: List[Dict[str, Any]] = []


    def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Helper to call OpenAI API. Handles batching automatically if list is small,
        """
        return embed_texts(self.client, texts, self.model)

    def index_documents(self, documents: List[Dict[str, Any]]) -> None:
        """
        1. Sends text to OpenAI to get vectors.
        2. Stores vectors in memory.
        """
        texts = [doc["text"] for doc in documents] 
        
        metadata = [{"chunk_id": doc.get("chunk_id")} for doc in documents]
        print(f"Embedding {len(documents)} documents using {self.model}...")
        
        embeddings = self._get_embeddings(texts)
        vectors = validate_vectors(embeddings, len(texts))
        # Commit all three fields together only after every batch validates.
        self.documents, self.document_metadata, self.document_vectors = texts, metadata, vectors
        print("Indexing complete. Vectors stored in memory.")
            

    def retrieve(self, query: str) -> List[str]:
        """
        1. Embeds the query.
        2. Calculates Cosine Similarity against all doc vectors.
        3. Returns top K texts.
        """
        if self.document_vectors is None or len(self.documents) == 0:
            print("Warning: Database is empty.")
            return []

        query_embeddings = self._get_embeddings([query])

        stored = validate_vectors(self.document_vectors, len(self.documents))
        query_vector = validate_vectors(query_embeddings, 1, stored.shape[1])

        similarities = cosine_similarity(query_vector, self.document_vectors).flatten()

        sorted_indices = similarities.argsort()
        
        top_indices = sorted_indices[-self.top_k:][::-1]

        results = []
        print(f"--- Semantic Search Results for: '{query}' ---")
        for idx in top_indices:
            score = similarities[idx]
            doc_text = self.documents[idx]
            print(f"Score: {score:.4f} | Text: {doc_text[:50]}...") 
            results.append({
                "text": doc_text,
                "chunk_id": self.document_metadata[idx].get("chunk_id"),
                "score": float(score)
            })
            
        return results
    
    def get_retrieved_scores(self, query: str) -> Dict[str, Any]:
        """
        Returns the cosine similarity scores for all documents given a query.
        Useful for evaluation purposes.
        """
        if self.document_vectors is None or len(self.documents) == 0:
            print("Warning: Database is empty.")
            return {"scores": []}

        query_embedding_list = self._get_embeddings([query])
        
        stored = validate_vectors(self.document_vectors, len(self.documents))
        query_vector = validate_vectors(query_embedding_list, 1, stored.shape[1])

        similarities = cosine_similarity(query_vector, self.document_vectors).flatten()

        average_score = np.mean(similarities) if len(similarities) > 0 else 0.0
        
        return {"scores": average_score}

