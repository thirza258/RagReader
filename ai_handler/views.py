from django.core.files.uploadedfile import UploadedFile
import os
import pandas as pd
from langchain_openai import OpenAIEmbeddings
from langchain.chat_models import init_chat_model
from langchain_community.document_loaders import WebBaseLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.tools import tool
from langgraph.graph import MessagesState, StateGraph
from langchain_core.messages import SystemMessage
from langgraph.prebuilt import ToolNode
from langgraph.graph import END
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.ai import AIMessage
from langchain_core.messages.tool import ToolMessage
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from ai_handler.models import ChatResponse, File
import logging
import PyPDF2
from langchain_core.prompts import PromptTemplate
import re
from io import BytesIO
import json
import faiss
import random
import numpy as np

logger = logging.getLogger(__name__)

class ChatSystem:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        self.model_name = None
        self.llm = None
        self.embeddings = None 
        self.vector_store = None
        self.graph = None
        self.documents = []
        self.vector_number = None
        self.length_of_chunk = 0
        
    def initialize_system(self, model_name, vector_number):
        self.model_name = model_name
        if(model_name == "OpenAI"):
            self.llm = init_chat_model("gpt-4o-mini", model_provider="openai")
        elif(model_name == "Mistral"):
            self.llm = init_chat_model("mistral-large-latest", model_provider="mistralai")
        elif(model_name == "Claude"):
            self.llm = init_chat_model("claude-3-5-haiku-20241022", model_provider="anthropic")
        else:
            raise Exception("Invalid model name")
        self.vector_number = vector_number
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
        
    def process_document(self, text_content, document_type):
        """
        Processes the given text content by splitting it into chunks and storing it in a vector database.

        Args:
            text_content (str | list): The text content (str for .pdf, .txt, .url) or 
                                       structured data (list for .csv) to be processed.
            document_type (str): The type of the document.
        """
        self.documents = [] # Initialize/clear documents for this run

        if document_type in [".pdf", ".txt", ".url"]:
            if not text_content:
                print("Warning: Empty text_content for document type", document_type)
                # self.documents remains empty
            elif not isinstance(text_content, str):
                raise TypeError(f"For document type {document_type}, text_content must be a string. Got {type(text_content)}")
            else:
                initial_chunk_size = min(500, len(text_content) // 2)
                actual_chunk_size = max(1, initial_chunk_size) # chunk_size must be > 0
                desired_chunk_overlap = 200
                # chunk_overlap must be < chunk_size
                actual_chunk_overlap = max(0, min(desired_chunk_overlap, actual_chunk_size - 1))
                
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=actual_chunk_size,
                    chunk_overlap=actual_chunk_overlap
                )
                split_texts = text_splitter.split_text(text_content)
                self.documents = [Document(page_content=chunk) for chunk in split_texts]

        elif document_type == ".csv":
            if not text_content:
                print("Warning: Empty text_content for document type .csv")
                # self.documents remains empty
            elif not isinstance(text_content, list): # Assuming text_content for CSV is a list of rows (e.g., dicts)
                raise TypeError(f"For document type .csv, text_content should be a list of rows. Got {type(text_content)}")
            else:
                try:
                    self.documents = [Document(page_content=json.dumps(row_data)) for row_data in text_content]
                except TypeError as e:
                    raise ValueError(f"Error serializing CSV row data to JSON: {e}. Ensure rows are JSON serializable.")
        else:
            # Or print a warning and leave self.documents empty
            # raise Exception(f"Unsupported document type: {document_type}")
            print(f"Warning: Unsupported document type: {document_type}. No documents processed.")
            self.vector_store = None
            return

        # --- Embedding and FAISS part ---
        if not self.documents:
            print("No documents were processed or found.")
            self.vector_store = None
            return

        # Extract the actual text content from the Document objects
        texts_to_embed = [doc.page_content for doc in self.documents if doc.page_content]

        if not texts_to_embed:
            print("All processed documents have empty page_content. Nothing to embed.")
            self.vector_store = None
            return
        
        try:
            # Now, texts_to_embed is a List[str], which is what embed_documents expects
            doc_embeddings = self.embeddings.embed_documents(texts_to_embed)
        except Exception as e:
            print(f"Error during self.embeddings.embed_documents: {e}")
            self.vector_store = None
            raise # Re-raise the exception to see the full traceback if needed

        if not doc_embeddings or not isinstance(doc_embeddings, list) or len(doc_embeddings) == 0:
            print("Embeddings generation failed or returned an empty list.")
            self.vector_store = None
            return
        
        # Check if the embeddings are in the expected format (list of lists of floats)
        if not isinstance(doc_embeddings[0], list) or not all(isinstance(val, float) for val in doc_embeddings[0]):
            print(f"Embeddings are not in the expected format (List[List[float]]). Got: {type(doc_embeddings[0])}")
            self.vector_store = None
            return

        embedding_dim = len(doc_embeddings[0])
        if embedding_dim == 0:
            print("Embedding dimension is 0. Cannot create FAISS index.")
            self.vector_store = None
            return
            
        self.vector_store = faiss.IndexFlatL2(embedding_dim)
        
        try:
            embeddings_np_array = np.array(doc_embeddings).astype(np.float32)
            if embeddings_np_array.ndim != 2 or embeddings_np_array.shape[1] != embedding_dim:
                print(f"Embeddings numpy array has unexpected shape: {embeddings_np_array.shape}. Expected (N, {embedding_dim})")
                self.vector_store = None
                return
            self.vector_store.add(embeddings_np_array)
            print(f"Successfully added {self.vector_store.ntotal} embeddings to FAISS index.")
        except Exception as e:
            print(f"Error adding embeddings to FAISS: {e}")
            self.vector_store = None
            raise

        
    def retrieve(self, query: str):
        """
        Retrieves relevant documents from the vector store based on a similarity search.

        Args:
            query (str): The search query.

        Returns:
            str: A formatted string containing retrieved document contents.
            list: A list of retrieved documents.
        """
        if self.length_of_chunk < self.vector_number:
            self.vector_number = max(1, self.length_of_chunk)  

        query_embedding = self.embeddings.embed_query(query)
        query_embedding = np.array(query_embedding).reshape(1, -1).astype(np.float32)
        
        distances, indices = self.vector_store.search(query_embedding, k=self.vector_number)
        retrieved_docs = [self.documents[i].page_content for i in indices[0] if i != -1]

        return retrieved_docs

    def query_and_respond(self, query: str):
        """
        Queries the chat system and returns a response.

        Args:
            query (str): The user's query.

        Returns:
            str: The response from the chat system.
        """
        if not self.llm or not self.vector_store:
            raise Exception("Chat system not initialized. Please upload a file first.")
        
        retrieved_docs = self.retrieve(query)
        print(query)
        print(retrieved_docs)
        
        prompt = PromptTemplate(
            template="""
                You are a RAG (Retrieval-Augmented Generation) Assistant. Your task is to answer questions based on the provided document content and user prompt. Follow these steps carefully:

                1. You will be given a set of document content in the following format:

                <docs_content>
                {retrieved_docs}
                </docs_content>
                
                User Query:
                <query>
                {query}
                </query>

                2. Carefully read and analyze the provided document content. This information will be the basis for answering the user's prompt.

                3. If the user asks **what the file is about** or **what the document is related to**, summarize its main topic concisely in one paragraph. Extract the most relevant portion of the document that gives a clear idea of its subject.

                4. If the user asks a specific question, answer using only the information in the `docs_content`. Do not use external knowledge.

                5. If the requested information is not available in the document, clearly state that it is not provided.

                6. Format your response in Markdown, ensuring clarity with appropriate headings, quotes, or lists when needed.

                7. Always enclose your response within `<answer>` tags, like this:

                <answer>

                # Document Summary

                This document discusses...

                </answer>

                or

                <answer>

                # Response

                As stated in the document:

                > "Relevant quote from docs_content"

                Further explanation...

                </answer>

                Ensure that responses are always relevant, concise, and well-structured.
                
                After processing the document content, below is the user prompt you need to answer:

            """,
            input_variables=["retrieved_docs", "query"]
        )
        
        chain = prompt | self.llm
        response = chain.invoke({
            "retrieved_docs": "\n".join(retrieved_docs),
            "query": query
        })
    
        return response


class FileSubmit(APIView):
    
    @staticmethod
    def extract_text(file_uploaded, file_extension):
        """
        Extract text content from different file types.

        Args:
            file_uploaded: The uploaded file object.
            file_extension: The file extension (e.g., '.pdf', '.txt', '.csv').

        Returns:
            str: The extracted text content.

        Raises:
            Exception: If the file type is unsupported or an error occurs during extraction.
        """
        file_uploaded.seek(0)  # Reset file pointer
        if file_extension == ".pdf":
            try:
                # Create a PDF reader object
                pdf_reader = PyPDF2.PdfReader(BytesIO(file_uploaded.read()))
                
                # Extract text from all pages
                text = []
                for page in pdf_reader.pages:
                    text.append(page.extract_text())
                
                return "\n".join(text)
            except Exception as e:
                raise Exception(f"Error reading PDF: {str(e)}")
        elif file_extension in [".txt"]:
            try:
                return file_uploaded.read().decode("utf-8")
            except UnicodeDecodeError:
                # If UTF-8 fails, try ISO-8859-1
                file_uploaded.seek(0)
                try:
                    return file_uploaded.read().decode("ISO-8859-1")
                except UnicodeDecodeError as e:
                    raise Exception("File encoding is not supported")
        elif file_extension == ".csv":
            try:
                df = pd.read_csv(file_uploaded)
                return df.to_json(orient="records")
            except Exception as e:
                raise Exception(f"Error reading CSV: {str(e)}")
        else:
            raise Exception("Unsupported file type")

    def post(self, request):
        """
        Handle file upload and processing.

        Args:
            request: The HTTP request object containing the file and metadata.

        Returns:
            Response: A Django REST Framework Response object with the result of the file upload process.
        """
        try:
            # Check if 'file' is present in the request
            if "file" in request.FILES:
                file_uploaded = request.FILES["file"]
            elif "file" in request.data:
                if isinstance(request.data["file"], str):
                    file_uploaded = BytesIO(request.data["file"].encode())
                else:
                    file_uploaded = BytesIO(request.data["file"])
            else:
                logger.error("No file found in the request.")
                return Response(
                    {"error": "No file found in the request"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            model_name = request.data["model_name"]
            vector_number = int(request.data["vector_number"])
            
            chat_system = ChatSystem.get_instance()
            chat_system.initialize_system(model_name, vector_number)
            
            # Save file
            if "file" in request.FILES:
                file = File(file=file_uploaded)
                try:
                    file.save()  # Attempt to save the file to the database
                except Exception as e:
                    logger.error(f"Error saving file: {e}")
                    return Response(
                        {"error": "Error saving file"}, 
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

                file_extension = os.path.splitext(file_uploaded.name)[1].lower()
                
                metadata = {}
                if isinstance(file_uploaded, UploadedFile):
                    metadata = {
                        "filename": file_uploaded.name,
                        "content_type": file_uploaded.content_type,
                        "size": file_uploaded.size,
                        "charset": file_uploaded.charset,
                    }
                else:
                    # Fallback for BytesIO or non-UploadedFile objects
                    metadata = {
                        "filename": getattr(file_uploaded, 'name', 'unknown'),
                        "size": file_uploaded.getbuffer().nbytes,
                        "content_type": "application/octet-stream",
                    }
                
                # Extract and process text
                try:
                    all_text = self.extract_text(file_uploaded, file_extension).strip()
                    all_text += f"\n\nThis Document or File Metadata: {json.dumps(metadata)}" 
                    # Process the document for chat system
                    chat_system.process_document(all_text, file_extension)
                except Exception as e:
                    logger.error(f"Error processing file: {e}")
                    return Response(
                        {"error": f"Error processing file: {str(e)}"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            elif "file" in request.data:
                file_extension = ".url"
                web_url = request.data["file"]  # Ensure this is a URL string

                if isinstance(web_url, bytes):
                    web_url = web_url.decode("utf-8")

                loader = WebBaseLoader(web_paths=(web_url,))
                document = loader.load()
                if not document or len(document) == 0:
                    raise ValueError("Failed to load content from the URL.")

                text_content = document[0].page_content if hasattr(document[0], "page_content") else ""

                if not text_content.strip():
                    raise ValueError("Loaded document content is empty.")

                chat_system.process_document(text_content, file_extension)
                
            # Prepare the response data
            
            data = {
                "model_name": model_name,
                "vector_number": vector_number
            }

            return Response(
                {
                    "status": 200,
                    "message": "File uploaded and processed successfully",
                    "data": data
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Error during file upload process: {e}")
            return Response(
                {"error": "An unexpected error occurred"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class GenerateChat(APIView):
    def post(self, request):
        try:
            chat_system = ChatSystem.get_instance()
            if not chat_system.llm :
                logger.error("Chat system not initialized. Please upload a file first.")
                return Response(
                    {"error": "Chat system not initialized. Please upload a file first."},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
            input_message = request.data["input_message"]
            ai_message_1 = ""
            tool_message = ""
            ai_message_2 = ""
            human_message = HumanMessage(content=input_message)

            data = {
                "human_message": human_message,
                "ai_message_1": ai_message_1,
                "tool_message": tool_message,  
                "ai_message_2": ai_message_2
            }
            
            ai_message_2 = chat_system.query_and_respond(input_message)
            ai_message_1 = ai_message_2

        
            return Response({
                "status": 200,
                "message": "Chat generated successfully",
                "data": ai_message_2,
            }, status=status.HTTP_200_OK)
                        
        except Exception as e:
            logger.error(f"Error generating chat: {e}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

class CleanChatSystem(APIView):
    def get(self, request):
        try:
            chat_system = ChatSystem.get_instance()
            chat_system.llm = None
            chat_system.embeddings = None
            chat_system.vector_store = None
            chat_system.graph = None
            chat_system.vector_number = None
            return Response(
                {"status": 200, "message": "Chat system cleaned successfully"},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Error cleaning chat system: {e}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
            