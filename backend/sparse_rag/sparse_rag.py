from typing import List, Dict, Any
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from rag.base_rag import BaseRAG

class SparseRAG(BaseRAG):
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the SparseRAG engine with TF-IDF.
        
        Config arguments expected:
        - top_k: (int) Number of documents to retrieve. Default is 3.
        - remove_stop_words: (bool) Whether to remove English stop words. Default is True.
        """
        super().__init__(config)
        self.documents = []
        self.vectorizer = None
        self.tfidf_matrix = None
        
        # Configuration defaults
        self.top_k = config.get("top_k", 3)
        self.remove_stop_words = "english" if config.get("remove_stop_words", True) else None

    def index_documents(self, documents: List[str]) -> None:
        """
        Builds the TF-IDF matrix for the provided documents.
        """
        print(f"Indexing {len(documents)} documents using TF-IDF...")
        
        self.documents = documents
        
        # Initialize the vectorizer
        # You can add n_gram_range=(1, 2) here if you want to capture phrases
        self.vectorizer = TfidfVectorizer(stop_words=self.remove_stop_words)
        
        # Fit and transform the documents into a sparse matrix
        # This creates a matrix where rows are documents and columns are tokens
        try:
            self.tfidf_matrix = self.vectorizer.fit_transform(documents)
            print("Indexing complete.")
        except ValueError as e:
            print(f"Error during indexing (list might be empty): {e}")

    def retrieve(self, query: str) -> List[str]:
        """
        Retrieves the top-k documents based on Cosine Similarity of TF-IDF vectors.
        """
        if self.vectorizer is None or self.tfidf_matrix is None:
            print("Warning: No documents indexed.")
            return []

        # 1. Transform the query into the same vector space as the documents
        query_vector = self.vectorizer.transform([query])

        # 2. Calculate Cosine Similarity between query and all docs
        # Result shape is (1, number_of_documents)
        similarity_scores = cosine_similarity(query_vector, self.tfidf_matrix).flatten()

        # 3. Sort results
        # argsort returns indices of values sorted in ascending order
        # We take the last 'top_k' indices and reverse them ([::-1]) to get descending order
        top_indices = similarity_scores.argsort()[-self.top_k:][::-1]

        # 4. Filter out results with 0 similarity (irrelevant docs)
        relevant_docs = []
        for idx in top_indices:
            if similarity_scores[idx] > 0:
                relevant_docs.append(self.documents[idx])
            else:
                # If the score is 0, the document shares no keywords with the query
                continue
                
        return relevant_docs