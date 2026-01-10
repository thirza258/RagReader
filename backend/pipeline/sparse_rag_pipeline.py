
from typing import Dict, Any
from backend.pipeline.base_pipeline import BasePipeline

class SparseRAGPipeline(BasePipeline):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)