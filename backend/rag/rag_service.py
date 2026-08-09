from pipeline.dense_rag_pipeline import DenseRAGPipeline
from pipeline.hybrid_rag_pipeline import HybridRAGPipeline
from pipeline.sparse_rag_pipeline import SparseRAGPipeline
from router.models import Document
from common.constant import CONFIG_VARIANTS, DEFAULT_TOP_K
import os
import glob

# How many candidates Hybrid's sub-engines feed the cross-encoder. Kept above
# the final depth so the reranker has something to actually rerank.
DEFAULT_CHILD_TOP_K = 10


def apply_retrieval_depth(engine, top_k: int = DEFAULT_TOP_K) -> None:
    """Set how many chunks `engine` returns, for this run.

    Engines are process-wide singletons, so call this before *every* variant
    rather than only when the depth changes — otherwise one run's Top-K leaks
    into the next. Derived values are computed from `top_k` alone, never from
    the engine's current state, so repeated calls can't drift.
    """
    rag = getattr(engine, "rag", None)
    if rag is None:
        return

    dense = getattr(rag, "dense_engine", None)
    sparse = getattr(rag, "sparse_engine", None)

    if dense is not None or sparse is not None:
        # Hybrid: the sub-engines build the candidate pool, the reranker trims
        # it to top_k. The pool has to be at least as deep as the final cut.
        child_depth = max(top_k * 2, DEFAULT_CHILD_TOP_K)
        rag.final_top_k = top_k
        rag.child_top_k = child_depth
        for child in (dense, sparse):
            if child is not None:
                child.top_k = child_depth
        return

    if hasattr(rag, "top_k"):
        rag.top_k = top_k


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
        """
        Instantiates pipelines based on the PIPELINE_VARIANTS list.
        """
        if os.getenv("RAG_DISABLE_ENGINE_INIT", "").lower() in ("1", "true"):
            print("RAG_DISABLE_ENGINE_INIT set — skipping engine initialization.")
            return

        class_map = {
            "Dense Retrieval": DenseRAGPipeline,
            "Sparse Retrieval": SparseRAGPipeline,
            "Hybrid Retrieval": HybridRAGPipeline,
        }

        for variant in CONFIG_VARIANTS:
            method_name = variant["method"]
            llm_model = variant["model"]
            
            pipeline_class = class_map.get(method_name)
            
            if not pipeline_class:
                print(f"⚠️ Warning: No class mapping found for '{method_name}'. Skipping.")
                continue

            instance_config = {
                "llm_model": llm_model,
                "model": "openai/text-embedding-3-small",
                "child_top_k": 10,
                "top_k": 5, 
                "chunk_strategy": "fixed",
                "chunk_size": 512,
                "overlap": 50,
            }

            if llm_model not in self.engines:
                self.engines[llm_model] = {}

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