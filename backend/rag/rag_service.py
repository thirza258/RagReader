from pipeline.dense_rag_pipeline import DenseRAGPipeline
from pipeline.hybrid_rag_pipeline import HybridRAGPipeline
from pipeline.sparse_rag_pipeline import SparseRAGPipeline
from pipeline.iterative_rag_pipeline import IterativeRAGPipeline
from pipeline.reranking_rag_pipeline import RerankingPipeline
from router.models import Document
from common.constant import CONFIG_VARIANTS


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
        
        # Storage: self.engines[llm_model][method_name]
        self.engines = {}
        self.initialize_engines()
        self._initialized = True

    def initialize_engines(self):
        """
        Instantiates pipelines based on the PIPELINE_VARIANTS list.
        """
        
        # 1. Map String Names to Python Classes
        class_map = {
            "Dense Retrieval": DenseRAGPipeline,
            "Sparse Retrieval": SparseRAGPipeline,
            "Hybrid Retrieval": HybridRAGPipeline,
            "Iterative Retrieval": IterativeRAGPipeline,
            "Reranking": RerankingPipeline 
        }

        # 2. Iterate through your constants
        for variant in CONFIG_VARIANTS:
            method_name = variant["method"]
            llm_model = variant["model"]
            
            pipeline_class = class_map.get(method_name)
            
            if not pipeline_class:
                print(f"⚠️ Warning: No class mapping found for '{method_name}'. Skipping.")
                continue

            instance_config = {
                "llm_model": llm_model,
                "model": "text-embedding-3-small",
                "top_k": 5, 
                "chunk_strategy": "paragraph",
                "chunk_size": 500,
                "overlap": 50,
            }

            # 4. Initialize the structure if not exists
            if llm_model not in self.engines:
                self.engines[llm_model] = {}

            # 5. Instantiate and Store (Lazy loading recommended, but here we init immediately)
            print(f"Initializing {method_name} with {llm_model}...")
            try:
                self.engines[llm_model][method_name] = pipeline_class(instance_config)
            except Exception as e:
                print(f"❌ Error initializing {method_name} ({llm_model}): {e}")

        print("--- RAG ENGINES READY ---")

    def get_engine(self, method: str, llm_model: str):
        """
        Retrieves a pipeline.
        Usage: registry.get_engine("Dense Retrieval", "gpt-4o-mini")
        """
        try:
            return self.engines[llm_model][method]
        except KeyError:
            available_methods = list(self.engines.get(llm_model, {}).keys())
            raise ValueError(
                f"Engine not found for Model: '{llm_model}' and Method: '{method}'. "
                f"Available methods for this model: {available_methods}"
            )



# Create a global instance
rag_registry = RAGRegistry()