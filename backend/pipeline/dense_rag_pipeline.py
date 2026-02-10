import os
import pickle
import logging
import uuid
from typing import Dict, Any # Assuming Django settings for base paths

from pipeline.base_pipeline import BasePipeline

from common.chunker import DocumentChunker
from dense_rag.dense_rag import DenseRAG
from ai_handler.llm import OpenAILLM, GeminiLLM, ClaudeLLM
from utils.insert_file import DataLoader

from router.models import (
    Document, 
    GuestUser, 
    VectorStore, 
    DocumentVector
)

logger = logging.getLogger(__name__)

class DenseRAGPipeline(BasePipeline):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        self.rag = DenseRAG(config)
        self.llm = self._initialize_llm(config.get("llm_model", "openai"))
        self.chunker = DocumentChunker(
            strategy=config.get("chunk_strategy", "paragraph"),
            chunk_size=config.get("chunk_size", 500),
            overlap=config.get("overlap", 50),
            embedding_client=self.rag.client 
        )
        self.loader = DataLoader()

        self.vector_store_root = config.get("vector_store_path", "./vector_stores")
        os.makedirs(self.vector_store_root, exist_ok=True)

    def _save_state(self, path: str):
        data = {
            "documents": self.rag.documents,
            "vectors": self.rag.document_vectors
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)

    def _load_state(self, path: str) -> bool:
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)

            self.rag.documents = data.get('documents', [])
            self.rag.document_vectors = data.get('vectors', [])
            return True
        except Exception as e:
            logger.error(f"Error loading state from {path}: {e}")
            return False

    def init(self, username: str) -> bool:
        """
        Prepares the vector store for the user.
        1. Checks DB for existing ready index.
        2. If missing, loads text, chunks, embeds, and saves to disk.
        3. Loads data into memory for this instance.
        """

        logger.info(f"Initializing Chat for {username}...")
        
        document = self.get_document(username)
        if not document:
            raise ValueError(f"No document found for user: {username}")

        doc_vector = DocumentVector.objects.filter(document=document, status="ready").last()
        if doc_vector:
            logger.info("Existing index found. Loading into memory.")
            success = self._load_state(doc_vector.vectorstore_location)
            if not success:
                raise RuntimeError("Index record exists but file load failed.")
            

        logger.info("Creating new index (Embedding)...")
        if not document.extracted_text_path:
            raise ValueError("Document has no text source path.")

        
        raw_text = self.loader.load(document.extracted_text_path)
        chunks = self.chunker.chunk(raw_text)

        self.rag.index_documents(chunks)

      
        file_name = f"{username}_{document.pk}_dense_{uuid.uuid4().hex[:6]}.pkl"
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
        logger.info("Initialization Complete.")
        return True
    
    def run(self, username: str, query: str) -> Dict[str, Any]:
        """
        Retrieves relevant documents and generates an answer.
        1. Optimizes query for better retrieval.
        2. Retrieves top K relevant docs.
        3. Generates answer using LLM.
        """
        logger.info(f"Running Chat for {username}...")
        if not self.rag.documents or len(self.rag.documents) == 0:
            logger.warning("No documents found in memory. Initializing...")
            document = self.get_document(username)
            if not document:
                raise ValueError(f"No document found for user: {username}")
            
            doc_vector = DocumentVector.objects.filter(document=document, status="ready").last()
            if not doc_vector:
                raise ValueError("No ready index found for this user.")

            success = self._load_state(doc_vector.vectorstore_location)
            if not success:
                raise RuntimeError("Index record exists but file load failed.")

            if not self.rag.documents or len(self.rag.documents) == 0:
                raise RuntimeError("State loaded from disk, but memory is still empty. The .pkl file might be corrupt or empty.")
        
        optimized_query = self.optimize_query(query)
        retrieved_docs = self.rag.retrieve(optimized_query)
        logger.info(f"Retrieved documents: {retrieved_docs}")

        if not retrieved_docs:
            raise ValueError("No relevant documents found.")

        context_str = "\n\n".join(retrieved_docs)
        answer = self.llm.rag_generate(optimized_query, context_str)
        return {
            "answer": answer,
            "context": retrieved_docs
        }

    def init_job(self, username: str, job=None) -> bool:
        """
        job: Instance of Job model (optional)
        """
        logger.info(f"Initializing Dense RAG for {username}...")
        
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
            logger.info(f"Documents: {self.rag.documents}")
            logger.info(f"Document vectors: {self.rag.document_vectors}")
            return True

        logger.info("Creating new index (Embedding)...")
        
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

        file_name = f"{username}_{document.pk}_dense_{uuid.uuid4().hex[:6]}.pkl"
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
        
        logger.info("Initialization Complete.")
        return True