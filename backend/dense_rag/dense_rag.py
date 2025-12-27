import os
import numpy as np
from typing import List, Dict, Any
from openai import OpenAI
from sklearn.metrics.pairwise import cosine_similarity
from backend.rag.base_rag import BaseRAG

class DenseRAG(BaseRAG):
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the DenseRAG engine using OpenAI Embeddings.
        
        Config arguments:
        - top_k: (int) Number of chunks to retrieve.
        - model: (str) OpenAI embedding model (default: "text-embedding-3-small").
        """
        super().__init__(config)
        
        # 1. Setup OpenAI Client
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables.")
        
        self.client = OpenAI(api_key=api_key)
        
        # 2. Configuration
        self.top_k = config.get("top_k", 3)
        self.model = config.get("model", "text-embedding-3-small")
        
        # 3. In-Memory Vector Store (Replace with Chroma/Pinecone for production)
        self.documents = []  # Stores the actual text
        self.document_vectors = None # Stores the numpy arrays

    def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Helper to call OpenAI API. Handles batching automatically if list is small,
        but for massive lists, you should chunk this manually.
        """
        # Clean newlines which can negatively affect embeddings
        cleaned_texts = [text.replace("\n", " ") for text in texts]
        
        try:
            response = self.client.embeddings.create(
                input=cleaned_texts,
                model=self.model
            )
            # Extract embeddings in order
            return [data.embedding for data in response.data]
        except Exception as e:
            print(f"Error calling OpenAI Embeddings API: {e}")
            return []

    def index_documents(self, documents: List[str]) -> None:
        """
        1. Sends text to OpenAI to get vectors.
        2. Stores vectors in memory.
        """
        print(f"Embedding {len(documents)} documents using {self.model}...")
        self.documents = documents
        
        # Call API
        embeddings = self._get_embeddings(documents)
        
        if embeddings:
            # Convert to numpy array for fast math
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

        # 1. Embed Query
        # Note: We pass [query] as a list because the API expects a list
        query_embedding_list = self._get_embeddings([query])
        
        if not query_embedding_list:
            return []
            
        query_vector = np.array(query_embedding_list)

        # 2. Calculate Cosine Similarity
        # shape: (1, n_docs)
        similarities = cosine_similarity(query_vector, self.document_vectors).flatten()

        # 3. Sort and Filter
        # Get indices of top_k scores (sorted ascending)
        sorted_indices = similarities.argsort()
        
        # Reverse to get descending (highest score first) and slice top_k
        top_indices = sorted_indices[-self.top_k:][::-1]

        results = []
        print(f"--- Semantic Search Results for: '{query}' ---")
        for idx in top_indices:
            score = similarities[idx]
            doc_text = self.documents[idx]
            print(f"Score: {score:.4f} | Text: {doc_text[:50]}...") # Debug print
            results.append(doc_text)
            
        return results