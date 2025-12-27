from abc import ABC, abstractmethod
from typing import List, Dict, Any, Union

class BaseRAG(ABC):
    """
    Abstract Base Class for all RAG methodologies.
    Enforces a standard structure: Index -> Retrieve -> Generate.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize with configuration (API keys, DB paths, model names).
        """
        self.config = config

    @abstractmethod
    def index_documents(self, documents: List[str]) -> None:
        """
        Step 1: Ingest data.
        - Sparse: Build BM25 index.
        - Dense: Create embeddings and store in Vector DB.
        - Graph: Extract entities and build Knowledge Graph.
        """
        pass

    @abstractmethod
    def retrieve(self, query: str) -> List[str]:
        """
        Step 2: Get relevant context.
        Returns a list of strings (chunks/documents).
        """
        pass

    def generate_answer(self, query: str, context: List[str]) -> str:
        """
        Step 3: Send to LLM. 
        This is usually shared across most RAG types, so it's a concrete method 
        here, but you can override it if needed.
        """
        # Placeholder for LLM call (e.g., OpenAI, Anthropic, Ollama)
        prompt = f"Context: {context}\n\nQuestion: {query}\nAnswer:"
        print(f"DEBUG: Sending prompt to LLM with {len(context)} chunks of context.")
        return "This is a mock LLM response."

    def run(self, query: str) -> str:
        """
        The main execution pipeline.
        """
        print(f"--- Running {self.__class__.__name__} ---")
        context = self.retrieve(query)
        answer = self.generate_answer(query, context)
        return answer