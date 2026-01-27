import os
import pickle
import logging
import uuid
from typing import Dict, Any, List

from pipeline.base_pipeline import BasePipeline

from common.chunker import DocumentChunker
from hybrid_rag.hybrid_rag import HybridRAG  
from ai_handler.llm import OpenAILLM
from utils.insert_file import DataLoader

from router.models import (
    Document, 
    GuestUser, 
    VectorStore, 
    DocumentVector
)

logger = logging.getLogger(__name__)

class HybridRAGPipeline(BasePipeline):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        self.rag = HybridRAG(config)
        
        self.llm = OpenAILLM(
            model=config.get("llm_model", "gpt-4o"),
            temperature=config.get("temperature", 0.0)
        )
        embedding_client = getattr(self.rag.dense_engine, 'client', None)
        
        self.chunker = DocumentChunker(
            strategy=config.get("chunk_strategy", "paragraph"),
            chunk_size=config.get("chunk_size", 500),
            overlap=config.get("overlap", 50),
            embedding_client=embedding_client
        )
        self.loader = DataLoader()

        # Base path for storing vector files (pickled)
        self.vector_store_root = config.get("vector_store_path", "./vector_stores")
        os.makedirs(self.vector_store_root, exist_ok=True)

    def _save_state(self, path: str):
        """
        Saves the state of both the Sparse and Dense engines.
        """
        data = {
            "sparse": {
                "documents": getattr(self.rag.sparse_engine, "documents", []),
                "model_state": self.rag.sparse_engine.__dict__
            },
            "dense": {
                "documents": getattr(self.rag.dense_engine, "documents", []),
                "vectors": getattr(self.rag.dense_engine, "document_vectors", [])
            }
        }
        try:
            with open(path, "wb") as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.error(f"Error saving pickle state: {e}")
            raise e

    def _load_state(self, path: str) -> bool:
        """
        Restores the state of both engines from disk.
        """
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            
            # Restore Sparse Engine
            if "sparse" in data:
                sparse_data = data["sparse"]
                # particular implementation depends on SparseRAG structure, 
                # but generally we restore documents and the index.
                self.rag.sparse_engine.documents = sparse_data.get("documents", [])
                # If specific attributes were saved in model_state, restore them
                if "model_state" in sparse_data:
                    self.rag.sparse_engine.__dict__.update(sparse_data["model_state"])

            # Restore Dense Engine
            if "dense" in data:
                dense_data = data["dense"]
                self.rag.dense_engine.documents = dense_data.get("documents", [])
                self.rag.dense_engine.document_vectors = dense_data.get("vectors", [])
            
            return True
        except Exception as e:
            logger.error(f"Error loading state from {path}: {e}")
            return False

    def init(self, username: str) -> bool:
        """
        Prepares the vector store (Hybrid) for the user.
        1. Checks DB for existing ready index.
        2. If missing, loads text, chunks, indexes (Sparse & Dense), and saves to disk.
        3. Loads data into memory for this instance.
        """

        logger.info(f"Initializing Hybrid Chat for {username}...")
        
        document = self.get_document(username)
        if not document:
            raise ValueError(f"No document found for user: {username}")

        doc_vector = DocumentVector.objects.filter(document=document, status="ready").last()
        if doc_vector:
            # It exists, just load it into memory
            logger.info("Existing index found. Loading into memory.")
            success = self._load_state(doc_vector.vectorstore_location)
            if not success:
                raise RuntimeError("Index record exists but file load failed.")
            return True

        # It doesn't exist, Create it (Heavy Operation)
        logger.info("Creating new Hybrid index...")
        if not document.extracted_text_path:
            raise ValueError("Document has no text source path.")

        # Load & Chunk
        raw_data = self.loader.process_input(document.extracted_text_path, username)
        raw_text = raw_data.get("text", "")
        
        if not raw_text:
             # Fallback if loader usage in pipeline differs slightly from direct usage
             raw_text = self.loader.load(document.extracted_text_path)

        chunks = self.chunker.chunk(raw_text)

        # Index Documents (This triggers both Sparse and Dense indexing)
        self.rag.index_documents(chunks)

        # Save to Disk
        file_name = f"{username}_{document.pk}_hybrid_{uuid.uuid4().hex[:6]}.pkl"
        save_path = os.path.join(self.vector_store_root, file_name)
        self._save_state(save_path)

        # Save to DB
        vs, _ = VectorStore.objects.get_or_create(base_path=self.vector_store_root)
        DocumentVector.objects.create(
            document=document,
            vectorstore=vs,
            vectorstore_location=save_path,
            document_location=document.extracted_text_path,
            status="ready"
        )
        logger.info("Hybrid Initialization Complete.")
        return True
    
    def run(self, username: str, query: str) -> Dict[str, Any]:
        """
        Retrieves relevant documents and generates an answer using Hybrid RAG.
        """
        logger.info(f"Running Hybrid Chat for {username}...")
        
        # Check if loaded (Checking dense docs is usually sufficient proxy for both)
        if not self.rag.dense_engine.documents or len(self.rag.dense_engine.documents) == 0:
            logger.warning("No documents found in memory. Initializing...")
            success = self.init(username)
            if not success:
                 # Fallback attempt to load if init returns True but state wasn't theoretically set (edge case)
                 document = self.get_document(username)
                 doc_vector = DocumentVector.objects.filter(document=document, status="ready").first()
                 if doc_vector:
                     self._load_state(doc_vector.vectorstore_location)
                 else:
                     raise ValueError("Initialization failed.")

        # 1. Optimize Query
        optimized_query = self.optimize_query(query)
        logger.info(f"Optimized Query: {optimized_query}")

        # 2. Retrieve (Hybrid: Sparse + Dense + RRF)
        retrieved_docs = self.rag.retrieve(optimized_query)

        if not retrieved_docs:
            # Fallback: try raw query if optimized returned nothing
            retrieved_docs = self.rag.retrieve(query)
            if not retrieved_docs:
                raise ValueError("No relevant documents found.")


        context_str = "\n\n".join(retrieved_docs)
        answer = self.llm.rag_generate(query, context_str)
        
        return {
            "answer": answer,
            "context": retrieved_docs
        }
    
    def init_job(self, username: str, job=None) -> bool:
        """
        Initializes the Hybrid RAG pipeline for a job.
        """
        logger.info(f"Initializing Hybrid RAG for {username}...")

        if job:
            job.progress = 10
            job.save()

        document = self.get_document(username)
        if not document:
            raise ValueError(f"No document found for user: {username}")

        doc_vector = DocumentVector.objects.filter(document=document, status="ready").last()

        if doc_vector:
            logger.info("Existing index found. Loading into memory.")
            
            if job:
                job.progress = 80
                job.save()
            
            logger.info(f"Loading state from {doc_vector.vectorstore_location}")
            success = self._load_state(doc_vector.vectorstore_location)
            if not success:
                logger.error("Index record exists but file load failed.")
                raise RuntimeError("Index record exists but file load failed.")
            logger.info(f"State loaded successfully from {doc_vector.vectorstore_location}")

            return True

        logger.info("Creating new Hybrid index...")
        
        if job:
            job.progress = 20
            job.save()

        logger.info(f"Loading text from {document.extracted_text_path}")

        if not document.extracted_text_path:
            raise ValueError("Document has no text source path.")

        raw_text = self.loader.load(document.extracted_text_path)

        if job:
            job.progress = 40
            job.save()

        chunks = self.chunker.chunk(raw_text)

        if job:
            job.progress = 50
            job.save()
            
        self.rag.index_documents(chunks)

        if job:
            job.progress = 90
            job.save()

        file_name = f"{username}_{document.pk}_hybrid_{uuid.uuid4().hex[:6]}.pkl"
        save_path = os.path.join(self.vector_store_root, file_name)
        self._save_state(save_path)

        vs, _ = VectorStore.objects.get_or_create(base_path=self.vector_store_root)
        DocumentVector.objects.create(
            document=document,
            vectorstore=vs,
            vectorstore_location=save_path,
            document_location=document.extracted_text_path,
            status="ready"
        )
        logger.info("Hybrid Initialization Complete.")
        return True