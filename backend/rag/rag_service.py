from backend.pipeline.dense_rag_pipeline import DenseRAGPipeline
from backend.pipeline.hybrid_rag_pipeline import HybridRAGPipeline
from backend.pipeline.sparse_rag_pipeline import SparseRAGPipeline
from backend.pipeline.iterative_rag_pipeline import IterativeRAGPipeline

class RAGRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.engines = {}
        self.initialize_engines()
        self._initialized = True

    def initialize_engines(self):
        configs = [
            {
                "llm_model": "gpt",
                "embedding_model": "text-embedding-3-small",
                "top_k": 5,
            },
            {
                "llm_model": "gemini",
                "embedding_model": "text-embedding-3-small",
                "top_k": 5,
            },
            {
                "llm_model": "claude",
                "embedding_model": "text-embedding-3-small",
                "top_k": 5,
            },
        ]

        engine_classes = {
            "dense": DenseRAGPipeline,
            "sparse": SparseRAGPipeline,
            "hybrid": HybridRAGPipeline,
            "iterative": IterativeRAGPipeline,
        }

        for config in configs:
            llm = config["llm_model"]
            self.engines[llm] = {}

            for engine_type, engine_cls in engine_classes.items():
                self.engines[llm][engine_type] = engine_cls(config)

        print("--- RAG ENGINES READY ---")

    def get_engine(self, engine_type: str, llm_model: str):
        try:
            return self.engines[llm_model][engine_type]
        except KeyError:
            raise ValueError(
                f"RAG engine not found: engine={engine_type}, llm={llm_model}"
            )

    def get_document(self, username: str) -> Document:
        return Document.objects.get(user=username)


# Create a global instance
rag_registry = RAGRegistry()