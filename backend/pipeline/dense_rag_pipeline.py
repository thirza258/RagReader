import os
import pickle
import logging
import uuid
from typing import Dict, Any, List, Optional
from django.conf import settings # Assuming Django settings for base paths

# Pipeline Base
from backend.pipeline.base_pipeline import BasePipeline
from backend.common.schema import VoteDecision

# Components
from backend.common.chunker import Chunker
from backend.dense_rag.dense_rag import DenseRAG
from backend.ai_handler.llm import OpenAILLM
from backend.utils.insert_file import DataLoader
from backend.common.schema import responses

# Models
from backend.router.models import (
    Document, 
    GuestUser, 
    VectorStore, 
    DocumentVector
)

logger = logging.getLogger(__name__)

class DenseRAGPipeline(BasePipeline):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        # 1. Initialize Components
        self.rag = DenseRAG(config)
        self.llm = OpenAILLM(
            model=config.get("llm_model", "gpt-4o"),
            temperature=config.get("temperature", 0.0)
        )
        self.chunker = Chunker(
            strategy=config.get("chunk_strategy", "paragraph"),
            chunk_size=config.get("chunk_size", 500),
            overlap=config.get("overlap", 50),
            embedding_client=self.rag.client 
        )
        self.loader = DataLoader()

        # Base path for storing vector files (pickled)
        # Ensure this directory exists
        self.vector_store_root = config.get("vector_store_path", "./vector_stores")
        os.makedirs(self.vector_store_root, exist_ok=True)

    def get_document(self, username: str) -> Optional[Document]:
        """Fetches the latest document for the user."""
        try:
            user = GuestUser.objects.filter(username=username).first()
            if not user:
                return None
            return Document.objects.filter(user=user).order_by('-created_at').first()
        except Exception as e:
            logger.error(f"Error fetching document: {e}")
            return None

    def _save_vectorstore_to_disk(self, path: str) -> None:
        """
        Persists the current in-memory RAG state (texts and vectors) to disk.
        """
        data = {
            "documents": self.rag.documents,
            "vectors": self.rag.document_vectors
        }
        with open(path, 'wb') as f:
            pickle.dump(data, f)
        logger.info(f"VectorStore saved to {path}")

    def _load_vectorstore_from_disk(self, path: str) -> bool:
        """
        Loads the RAG state from disk into memory.
        """
        try:
            if not os.path.exists(path):
                logger.error(f"Vector store file not found at {path}")
                return False

            with open(path, 'rb') as f:
                data = pickle.load(f)
            
            # Restore state to the RAG engine
            self.rag.documents = data["documents"]
            self.rag.document_vectors = data["vectors"]
            logger.info(f"VectorStore loaded from {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load vector store: {e}")
            return False

    def _get_or_create_vector_index(self, document: Document) -> bool:
        """
        Checks for an existing VectorStore/DocumentVector relation.
        - If exists: Loads it.
        - If not: Indexes text, creates DB entries, saves file, then loads.
        """
        # 1. Check if DocumentVector exists and is ready
        doc_vector = DocumentVector.objects.filter(
            document=document, 
            status="ready"
        ).first()

        if doc_vector:
            # Load existing
            logger.info(f"Found existing VectorStore for doc {document.id}")
            return self._load_vectorstore_from_disk(doc_vector.vectorstore_location)
        
        # 2. If not, create new Index
        logger.info(f"No vector store found. Creating new index for {document.name}...")
        
        if not document.extracted_text_path:
            logger.error("Document has no text path.")
            return False

        try:
            # A. Load and Chunk
            raw_text = self.loader.load(document.extracted_text_path)
            chunks = self.chunker.chunk(raw_text)
            
            # B. Embed (In-Memory)
            self.rag.index_documents(chunks)
            
            # C. Define Save Path
            file_name = f"{document.user.username}_{document.id}_{uuid.uuid4().hex[:8]}.pkl"
            save_path = os.path.join(self.vector_store_root, file_name)
            
            # D. Save to Disk
            self._save_vectorstore_to_disk(save_path)
            
            # E. Update Database Models
            # Create VectorStore entry
            vs = VectorStore.objects.create(base_path=self.vector_store_root)
            
            # Create DocumentVector link
            DocumentVector.objects.create(
                document=document,
                vectorstore=vs,
                vectorstore_location=save_path,
                document_location=document.extracted_text_path,
                status="ready"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to create vector index: {e}")
            # Optionally create a failed record
            return False

    def optimize_query(self, query: str) -> str:
        try:
            return self.llm.prompt_generate(query)
        except:
            return query

    def run(self, query: str, username: str = None) -> Dict[str, Any]:
        if not username:
             return responses.response_400(
                error="Username required."
            )

        # 1. Get User Document
        document = self.get_document(username)
        if not document:
            return responses.response_404(
                
                error="No documents found for this user."
            )

        # 2. Ensure Vector Store is Loaded (from Disk or Created)
        success = self._get_or_create_vector_index(document)
        if not success:
            return responses.response_500(
                
                error="Failed to process or load document index."
            )

        # 3. Standard RAG Flow (Optimized Query -> Retrieve -> Generate -> Vote)
        optimized_query = self.optimize_query(query)
        retrieved_docs = self.rag.retrieve(optimized_query)

        if not retrieved_docs:
            return responses.response_404(
                error="No relevant context found."
            )

        context_str = "\n\n".join(retrieved_docs)
        
        answer = self.llm.rag_generate(query=query, context=context_str)

        return responses.response_200(response=answer)

    