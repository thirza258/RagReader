import numpy as np
from typing import List, Dict, Any, Optional
from django.conf import settings
from openai import OpenAI
from sklearn.metrics.pairwise import cosine_similarity
from rag.base_rag import BaseRAG

class DenseRAG(BaseRAG):
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the DenseRAG engine using OpenRouter.
        
        Config arguments:
        - top_k: (int) Number of chunks to retrieve.
        - model: (str) OpenRouter model string 
                 (e.g., "openai/text-embedding-3-small", "qwen/qwen3-embedding-8b")
        """
        super().__init__(config)
        
        api_key = settings.OPENROUTER_API_KEY
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY not found in settings.")
        
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key
        )
        
        self.top_k = config.get("top_k", 3)
        self.model = config.get("model", "openai/text-embedding-3-small")
        
        self.documents: List[str] =[]  
        self.document_vectors: Optional[np.ndarray] = None 
        self.document_metadata: List[Dict[str, Any]] = []


    def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Helper to call OpenAI API. Handles batching automatically if list is small,
        """
        cleaned_texts = [text.replace("\n", " ") for text in texts]
        
        try:
            response = self.client.embeddings.create(
                input=cleaned_texts,
                model=self.model
            )
            return [data.embedding for data in response.data]
        except Exception as e:
            print(f"Error calling OpenAI Embeddings API: {e}")
            return []

    def index_documents(self, documents: List[Dict[str, Any]]) -> None:
        """
        1. Sends text to OpenAI to get vectors.
        2. Stores vectors in memory.
        """
        texts = [doc["text"] for doc in documents] 
        
        self.document_metadata = [{"chunk_id": doc.get("chunk_id")} for doc in documents]
        print(f"Embedding {len(documents)} documents using {self.model}...")
        
        self.documents = texts
        
        embeddings = self._get_embeddings(texts)
        
        if embeddings:
            self.document_vectors = np.array(embeddings)
            print("Indexing complete. Vectors stored in memory.")
        else:
            print("Indexing failed: No embeddings returned.")
            

    def retrieve(self, query: str) -> List[str]:
        """
        1. Embeds the query.
        2. Calculates Cosine Similarity against all doc vectors.
        3. Returns top K texts.
        """
        if self.document_vectors is None or len(self.documents) == 0:
            print("Warning: Database is empty.")
            return []

        query_embedding_list = self._get_embeddings([query])[0]
        
        if not query_embedding_list:
            return []
            
        query_vector = np.array(query_embedding_list).reshape(1, -1) 

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
        
        if not query_embedding_list:
            return {"scores": []}
            
        query_vector = np.array(query_embedding_list)

        similarities = cosine_similarity(query_vector, self.document_vectors).flatten()

        average_score = np.mean(similarities) if len(similarities) > 0 else 0.0
        
        return {"scores": average_score}
    