import os
import networkx as nx
import numpy as np
import faiss
from typing import List, Dict, Any, Tuple
from openai import OpenAI

from backend.rag.base_rag import BaseRAG
from backend.graph_rag.helper import text_to_networkx

class GraphRAG(BaseRAG):
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes Graph RAG.
        
        Config:
        - embedding_dim: (int) Dimension of embeddings (1536 for OpenAI small).
        - max_hops: (int) How deep to traverse from the found node (default 1).
        """
        super().__init__(config)
        
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key)
        
        # Graph Storage
        self.graph = nx.Graph()
        
        # Vector Index for Nodes (FAISS)
        self.embedding_dim = config.get("embedding_dim", 1536)
        self.index = faiss.IndexFlatL2(self.embedding_dim)
        
        # Mapping FAISS ID -> Node Name
        self.node_id_to_name = {}
        self.current_id = 0
        
        self.model = config.get("model", "text-embedding-3-small")
        self.max_hops = config.get("max_hops", 1)

    def _get_embedding(self, text: str) -> np.ndarray:
        """Helper to get single vector."""
        text = text.replace("\n", " ")
        resp = self.client.embeddings.create(input=[text], model=self.model)
        return np.array(resp.data[0].embedding, dtype='float32')

    def index_documents(self, documents: List[str]) -> None:
        """
        1. Extract Nodes/Edges using LLM (helper).
        2. Merge into NetworkX graph.
        3. Embed Node names and add to FAISS.
        """
        print("Building Knowledge Graph from documents...")
        
        # 1. Build the Graph structure
        for i, doc in enumerate(documents):
            print(f"Processing document {i+1}/{len(documents)}...")
            # Use the helper function created previously
            doc_graph = text_to_networkx(doc, self.client)
            # Merge new sub-graph into main graph
            self.graph = nx.compose(self.graph, doc_graph)

        print(f"Graph built. Nodes: {self.graph.number_of_nodes()}, Edges: {self.graph.number_of_edges()}")

        # 2. Embed Nodes for Retrieval
        # We need to find the "entry point" into the graph based on the query.
        # We do this by embedding the Node Labels (e.g., "Elon Musk", "SpaceX").
        print("Embedding graph nodes for retrieval...")
        
        node_names = list(self.graph.nodes())
        if not node_names:
            print("Warning: Graph is empty.")
            return

        # In production, batch this. For template, we loop.
        vectors = []
        for name in node_names:
            vec = self._get_embedding(name)
            vectors.append(vec)
            
            # Store mapping
            self.node_id_to_name[self.current_id] = name
            self.current_id += 1
            
        # Add to FAISS
        if vectors:
            # Ensure consistent shape and dtype
            vector_matrix = np.stack(vectors).astype(np.float32)

            # Safety checks
            assert vector_matrix.ndim == 2
            assert vector_matrix.shape[1] == self.index.d

            self.index.add(x=vector_matrix, n=vector_matrix.shape[0])
            print("Node embeddings indexed in FAISS.")

    def retrieve(self, query: str) -> List[str]:
        """
        1. Search FAISS for closest Entity (Node).
        2. Traverse graph to find neighbors (Relationships).
        3. Return textual description of relationships.
        """
        if self.index.ntotal == 0:
            return []

        print(f"--- Graph Search for: '{query}' ---")

        # 1. Embed Query
        query_vec = np.asarray(
            self._get_embedding(query),
            dtype=np.float32
        ).reshape(1, -1)
        
        # 2. Search FAISS (Find top 3 closest entities)
        k = 3
        distances, indices = self.index.search(query_vec, k) # type: ignore
        
        found_nodes = []
        for idx in indices[0]:
            if idx in self.node_id_to_name:
                found_nodes.append(self.node_id_to_name[idx])
        
        print(f"Found entry nodes: {found_nodes}")

        # 3. Traverse Graph (Context Expansion)
        context_sentences = []
        visited_edges = set()

        for node in found_nodes:
            # Get neighbors (1-hop)
            if node in self.graph:
                neighbors = self.graph[node]
                
                for neighbor, attrs in neighbors.items():
                    # Check edge uniqueness to avoid duplicates
                    edge_key = tuple(sorted((node, neighbor)))
                    if edge_key in visited_edges:
                        continue
                    visited_edges.add(edge_key)

                    # Construct text context from edge attributes
                    relation = attrs.get('relation', 'related to')
                    sentence = f"{node} is {relation} {neighbor}."
                    context_sentences.append(sentence)

        return context_sentences