import pickle
import os
import re
from typing import List, Dict, Any
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from rank_bm25 import BM25Okapi
from rag.base_rag import BaseRAG

try:
    nltk.data.find('corpora/stopwords')
    nltk.data.find('tokenizers/punkt')
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    nltk.download('stopwords', quiet=True)
    nltk.download('punkt', quiet=True)
    nltk.download('punkt_tab', quiet=True)

class SparseRAG(BaseRAG):
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the SparseRAG engine with BM25.
        """
        super().__init__(config)
        self.documents = []
        self.bm25 = None
        
        self.top_k = config.get("top_k", 3)
        
        if config.get("remove_stop_words", True):
            self.stop_words = set(stopwords.words('english'))
        else:
            self.stop_words = set()

    def _tokenize(self, text: str) -> List[str]:
        """
        Helper to lowercase, remove punctuation, and tokenize text.
        """
        text = re.sub(f'[^a-zA-Z0-9\s]', '', text.lower())
        tokens = word_tokenize(text)
        return [w for w in tokens if w not in self.stop_words]

    def index_documents(self, documents: List[str]) -> None:
        """
        Builds the BM25 index for the provided documents.
        """
        if not documents:
            print("Warning: Document list is empty.")
            return

        print(f"Indexing {len(documents)} documents using BM25...")
        
        self.documents = documents
        tokenized_corpus = [self._tokenize(doc) for doc in documents]
        
        try:
            self.bm25 = BM25Okapi(tokenized_corpus)
            print("Indexing complete.")
        except Exception as e:
            print(f"Error during indexing: {e}")

    def retrieve(self, query: str) -> List[str]:
        """
        Retrieves the top-k documents based on BM25 scores.
        """
        if self.bm25 is None:
            print("Warning: No documents indexed.")
            return []
            
        tokenized_query = self._tokenize(query)
        
        scores = self.bm25.get_scores(tokenized_query)
        
        top_indices = scores.argsort()[-self.top_k:][::-1]

        relevant_docs = []
        for idx in top_indices:
            if scores[idx] > 0:
                relevant_docs.append(self.documents[idx])
                
        return relevant_docs