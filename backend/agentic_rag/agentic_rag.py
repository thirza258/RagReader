from rag.base_rag import BaseRAG
from typing import Dict, Any

class AgenticRAG(BaseRAG):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
