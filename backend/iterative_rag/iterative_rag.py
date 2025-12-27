import os
import json
from typing import List, Dict, Any
from openai import OpenAI
from backend.rag.base_rag import BaseRAG
from backend.rag.dense_rag import DenseRAG

class IterativeRAG(BaseRAG):
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes Iterative RAG.
        
        It wraps a DenseRAG engine and adds a feedback loop.
        
        Config:
        - max_retries: (int) Maximum number of retrieval loops (default 3).
        - model: (str) LLM model for the reasoning steps (e.g., gpt-4o).
        """
        super().__init__(config)
        
        # 1. Initialize the internal Retrieval Engine
        print("Initializing internal DenseRAG engine for Iterative Search...")
        self.dense_engine = DenseRAG(config)
        
        # 2. Setup Logic Controller
        self.max_retries = config.get("max_retries", 3)
        self.model = config.get("llm_model", "gpt-4o") # Stronger model needed for reasoning
        
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def index_documents(self, documents: List[str]) -> None:
        """
        Delegates indexing to the internal DenseRAG engine.
        """
        self.dense_engine.index_documents(documents)

    def retrieve(self, query: str) -> List[str]:
        """
        The Iterative Loop:
        Retrieve -> Evaluate -> Reformulate -> Retrieve -> ...
        """
        print(f"--- Starting Iterative Loop for: '{query}' ---")
        
        current_query = query
        collected_context = set() # Use set to avoid duplicates
        final_context_list = []
        
        for i in range(self.max_retries):
            print(f"\n[Iteration {i+1}/{self.max_retries}] Searching for: '{current_query}'")
            
            # 1. Retrieve using Dense RAG
            new_docs = self.dense_engine.retrieve(current_query)
            
            # 2. Add unique docs to our collection
            for doc in new_docs:
                if doc not in collected_context:
                    collected_context.add(doc)
                    final_context_list.append(doc)
            
            # 3. Evaluate Sufficiency
            # We treat the list of strings as the current knowledge state
            context_text = "\n---\n".join(final_context_list)
            
            if self._is_context_sufficient(query, context_text):
                print(">> LLM Judge: Context is sufficient. Stopping loop.")
                break
            
            # 4. If not sufficient (and not last loop), generate new query
            if i < self.max_retries - 1:
                print(">> LLM Judge: Information missing. Generating follow-up query...")
                current_query = self._generate_followup_query(query, context_text)
            else:
                print(">> Max retries reached. Returning what we have.")

        return final_context_list

    def _is_context_sufficient(self, original_query: str, context: str) -> bool:
        """
        Asks the LLM if the current context answers the question.
        Returns True/False.
        """
        prompt = f"""
        You are an evaluator.
        User Question: "{original_query}"
        Current Retrieved Context:
        {context}
        
        Does the context contain enough information to answer the question? 
        Reply with JSON: {{"sufficient": true}} or {{"sufficient": false}}.
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            return result.get("sufficient", False)
        except Exception:
            # Fallback to False if JSON parsing fails to keep trying
            return False

    def _generate_followup_query(self, original_query: str, context: str) -> str:
        """
        Asks the LLM to generate a search query for the MISSING information.
        """
        prompt = f"""
        User Question: "{original_query}"
        Current Context:
        {context}
        
        The context is missing key details. Generate a SHORT Google-search-style query 
        to find the missing information. Do not explain, just output the query.
        """
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()