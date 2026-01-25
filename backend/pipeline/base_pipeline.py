from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from router.models import Document
from router.models import Job

class BasePipeline(ABC):
    """
    The High-Level Controller.
    It orchestrates the RAG Engine (retrieval), the LLM (generation),
    and the Reranker (refinement).
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # Common state storage
        self.llm = None         
        self.reranker = None    # e.g., CrossEncoder

    # --- Phase 1: Ingestion (Data Loading) ---

    @abstractmethod
    def get_document(self, username: str) -> Document | None:
        """
        Gets the document from the database.
        """
        

    @abstractmethod
    def _save_state(self, path: str):
        pass

    @abstractmethod
    def _load_state(self, path: str) -> bool:
        pass

    # --- Phase 2: Inference (Running the RAG) ---

    @abstractmethod
    def optimize_query(self, query: str) -> str:
        """
        Optional: Uses LLM to rewrite the user query for better search.
        Replaces your 'parse_query'.
        """
        pass

    @abstractmethod
    def run(self, username:str, query: str) -> Dict[str, Any]:
        """
        The main execution flow:
        Query -> Retrieve -> Generate Answer.
        Replaces your 'parse_response'.
        """
        pass

    @abstractmethod
    def init(self, username: str) -> bool:
        """
        Initializes the pipeline by loading the state from the database
        .
        """
        pass
