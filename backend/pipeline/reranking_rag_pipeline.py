from typing import Dict, Any
from pipeline.base_pipeline import BasePipeline

class RerankingPipeline(BasePipeline):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)