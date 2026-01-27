from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from router.models import Document, GuestUser
from router.models import Job
import logging

logger = logging.getLogger(__name__)

class BasePipeline(ABC):
    """
    The High-Level Controller.
    It orchestrates the RAG Engine (retrieval), the LLM (generation),
    and the Reranker (refinement).
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.llm = None         
        self.reranker = None    

    def get_document(self, username: str) -> Document | None:
        try:
            user = GuestUser.objects.filter(username=username).first()
            if not user:
                return None
            return Document.objects.filter(user=user).last()
        except Exception as e:
            logger.error(f"Error getting document for {username}: {e}")
            return None

    def optimize_query(self, query: str) -> str:
        """
        Optimizes the query for better retrieval.
        Returns ONLY the optimized string.
        """
        prompt = (
            "You are a query optimization tool for a Vector Database. "
            "Your task is to rewrite the user's input into a single, keyword-rich sentence "
            "that is optimized for cosine similarity search."
            "\n\n"
            "Rules:\n"
            "1. Output ONLY the rewritten query.\n"
            "2. Do NOT provide explanations, bullet points, or numbering.\n"
            "3. Do NOT use quotes around the output.\n"
            "4. Keep the language the same as the input.\n"
            "\n"
            f"Input: {query}\n"
            "Output:"
        )
        
        raw_response = self.llm.prompt_generate(prompt)
        
        optimized_query = self._validate_and_clean_query(raw_response, query)
        
        logger.info(f"Original Query: '{query}' -> Optimized: '{optimized_query}'")
        return optimized_query

    def _validate_and_clean_query(self, response: str, original_query: str) -> str:
        """
        Ensures the response is a clean, single-line string.
        If the LLM hallucinates or fails, fallback to the original query.
        """
        if not response:
            return original_query

        cleaned = response.strip()

        cleaned = cleaned.replace('"', '').replace("'", "")

        if "\n" in cleaned:
            cleaned = cleaned.split("\n")[0]

        prefixes = ["Here is", "Optimized query:", "Answer:"]
        for prefix in prefixes:
            if cleaned.lower().startswith(prefix.lower()):
                cleaned = cleaned[len(prefix):].strip()

        if len(cleaned) > 200: 
            logger.warning(f"Optimization failed (result too long). Fallback to original.")
            return original_query

        return cleaned

    @abstractmethod
    def _save_state(self, path: str):
        pass

    @abstractmethod
    def _load_state(self, path: str) -> bool:
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
