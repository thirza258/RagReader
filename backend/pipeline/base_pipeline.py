from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class BasePipeline(ABC):
    """
    The High-Level Controller.
    It orchestrates the RAG Engine (retrieval), the LLM (generation),
    and the Reranker (refinement).
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # Common state storage
        self.llm = None         # e.g., OpenAILLM, GeminiLLM
        self.reranker = None    # e.g., CrossEncoder

    # --- Phase 1: Ingestion (Data Loading) ---

    @abstractmethod
    def load_file(self, file_path: str) -> List[str]:
        """
        Reads a file (PDF, TXT, JSON) and returns raw text strings.
        Replaces your 'parse_file'.
        """
        pass

    @abstractmethod
    def index_data(self, data: List[str]) -> None:
        """
        Takes raw text, chunks it, and saves it to the DB.
        Replaces your 'parse_chunk' + 'parse_document'.
        """
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
    def run(self, query: str) -> Dict[str, Any]:
        """
        The main execution flow:
        Query -> Retrieve -> Rerank -> Generate Answer.
        Replaces your 'parse_response'.
        """
        pass

    # --- Phase 3: Evaluation (Optional) ---
    
    def evaluate_answer(self, query: str, context: str, answer: str) -> Dict[str, Any]:
        """
        Checks if the answer is grounded in context.
        Replaces your 'parse_vote'.
        """
        # This can be concrete because logic is often shared
        if not self.llm:
            return {"error": "No LLM loaded"}
        
        # Use your LLM's voting capability here
        return self.llm.vote_generate(query, context, answer)