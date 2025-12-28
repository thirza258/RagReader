

class RAGRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RAGRegistry, cls).__new__(cls)
            cls._instance.initialize_engines()
        return cls._instance

    def initialize_engines(self):
        print("--- LOADING RAG ENGINES ---")
        # Shared Config
        config = {
            "top_k": 3,
            "llm_model": "gpt-4o",
            "model": "text-embedding-3-small"
        }
        
        # Initialize all engines and keep them in memory
        self.engines = {
            "dense": DenseRAG(config),
            "sparse": SparseRAG(config),
            "graph": GraphRAG(config),
            "hybrid": HybridRAG(config),
            # "iterative": IterativeRAG(config) # Add if needed
        }
        print("--- RAG ENGINES READY ---")

    def get_engine(self, engine_type: str):
        return self.engines.get(engine_type)

    def index_all(self, documents):
        """Helper to update ALL indexes when new data comes in"""
        for name, engine in self.engines.items():
            print(f"Indexing data for {name}...")
            engine.index_documents(documents)

# Create a global instance
rag_registry = RAGRegistry()