from backend.pipeline.base_pipeline import BasePipeline
from typing import Dict, Any, List
from backend.common.chunker import Chunker
from backend.common.prompt_builder import prompt_generator, rag_prompt, vote_prompt
from backend.ai_handler.llm import OpenAILLM
from backend.agent_voter.voter import Voter
from backend.common.schema import RAGResponse, VoteDecision
from backend.dense_rag.dense_rag import DenseRAG
from backend.utils.insert_file import DataLoader


class DenseRAGPipeline(BasePipeline):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    def load_file(self, file_path: str) -> List[str]:
        