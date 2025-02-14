from django.shortcuts import render
import os
import pandas as pd
from langchain_openai import ChatOpenAI
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings
import bs4
from langchain import hub
from langchain.chat_models import init_chat_model
from langchain_community.document_loaders import WebBaseLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from typing_extensions import List, TypedDict
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
import re
from io import BytesIO
import json
import random

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
            text_content (str): The text content to be processed.
        """
        self.vector_store = InMemoryVectorStore(self.embeddings)
        
        self.all_docs = [] 
        
        if document_type in [".pdf", ".txt", ".url"]:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=min(500, len(text_content) // 2),
                chunk_overlap=200
            )
            docs = [Document(page_content=chunk) for chunk in text_splitter.split_text(text_content)]

        elif document_type == ".csv":
            docs = [Document(page_content=json.dumps(chunks)) for chunks in text_content]

        else:
            raise Exception("Unsupported document type")
        
        self.length_of_chunk = len(docs)
        self.all_docs.extend(docs)  
        self.vector_store.add_documents(docs)
        self.setup_graph()

    def setup_graph(self):
        """
        Sets up the retrieval-augmented generation (RAG) graph for handling queries 
        using a language model and vector search.
        """

        @tool(response_format="content_and_artifact")
        def retrieve(query: str):
            """
            Retrieves relevant documents from the vector store based on a similarity search.

            Args:
                query (str): The search query.

            Returns:
                str: A formatted string containing retrieved document contents.
                list: A list of retrieved documents.
            """
            if self.length_of_chunk < self.vector_number:
                self.vector_number = max(1, self.length_of_chunk)  # Ensure at least 1

            retrieved_docs = self.vector_store.similarity_search(query, k=self.vector_number)
            

            # If retrieval fails, try a generic query
            if not retrieved_docs:
                retrieved_docs = self.vector_store.similarity_search("Summarize", k=self.vector_number)

            # Final fallback: return a random document if still empty
            if not retrieved_docs and self.all_docs:
                retrieved_docs = [random.choice(self.all_docs)]  # Pick 1 random document

            # Ensure a valid response
            if retrieved_docs:
                serialized = "\n\n".join(
                    f"Source: {doc.metadata}\nContent: {doc.page_content}"
                    for doc in retrieved_docs
                )
            else:
                serialized = "No relevant documents found."

            return serialized, retrieved_docs

        graph_builder = StateGraph(MessagesState)

        def query_or_respond(state: MessagesState):
            """
            Handles incoming queries, invoking the language model to generate responses.

            Args:
                state (MessagesState): The current state of messages in the conversation.

            Returns:
                dict: A dictionary containing the response messages.
            """
            llm_with_tools = self.llm.bind_tools([retrieve])
            response = llm_with_tools.invoke(state["messages"])
            return {"messages": [response]}

        tools = ToolNode([retrieve])

        def generate(state: MessagesState):
            """
            Generates responses using the language model based on retrieved documents.

            Args:
                state (MessagesState): The current state of messages.

            Returns:
                dict: A dictionary containing the AI-generated response.
            """
            recent_tool_messages = []
            for message in reversed(state["messages"]):
                if message.type == "tool":
                    recent_tool_messages.append(message)
                else:
                    break
            tool_messages = recent_tool_messages[::-1]

            docs_content = "\n\n".join(doc.content for doc in tool_messages)
            system_message_content = (
                f"""
                You are a RAG (Retrieval-Augmented Generation) Assistant. Your task is to answer questions based on the provided document content and user prompt. Follow these steps carefully:

                1. You will be given a set of document content in the following format:

                <docs_content>
                {docs_content}
                </docs_content>

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

                """
            )

            conversation_messages = [
                message
                for message in state["messages"]
                if message.type in ("human", "system")
                or (message.type == "ai" and not message.tool_calls)
            ]
            
            prompt = [SystemMessage(system_message_content)] + conversation_messages

            response = self.llm.invoke(prompt)
            return {"messages": [response]}

        graph_builder.add_node(query_or_respond)
        graph_builder.add_node(tools)
        graph_builder.add_node(generate)

        graph_builder.set_entry_point("query_or_respond")
        graph_builder.add_conditional_edges(
            "query_or_respond",
            tools_condition,
            {END: END, "tools": "tools"},
        )
        graph_builder.add_edge("tools", "generate")
        graph_builder.add_edge("generate", END)

        self.graph = graph_builder.compile()


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
            
            
            # Initialize the chat system
            print("Getting chat system instance...")
            chat_system = ChatSystem.get_instance()
            print("Initializing chat system...")
            chat_system.initialize_system(model_name, vector_number)
            print("Chat system initialized")
            
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
                
                # Extract and process text
                try:
                    all_text = self.extract_text(file_uploaded, file_extension)
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
            if not chat_system.llm or not chat_system.graph:
                logger.error("Chat system not initialized. Please upload a file first.")
                return Response(
                    {"error": "Chat system not initialized. Please upload a file first."},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
            input_message = request.data["input_message"]
            ai_message_1 = None
            tool_message = None
            ai_message_2 = None
            
            for step in chat_system.graph.stream(
                {"messages": [HumanMessage(content=input_message)]},
                stream_mode="values",
            ):
                messages = step["messages"]

                for message in messages:
                    if isinstance(message, HumanMessage):
                        human_message = message.content
                    elif isinstance(message, AIMessage) and ai_message_1 is None:
                        if isinstance(message.content, list):  
                            # Extract text from list items if it's a list
                            ai_message_1 = "\n".join(
                                content["text"] if isinstance(content, dict) and "text" in content else str(content)
                                for content in message.content
                            )
                        else:
                            ai_message_1 = message.content  # Directly assign if it's a string
                        
                        if chat_system.model_name == "Claude" and "retrieve" in ai_message_1:
                            ai_message_1 = "Warning"
                    elif isinstance(message, ToolMessage):
                        tool_message = message.content
                    elif isinstance(message, AIMessage):
                        if isinstance(message.content, list):  
                            # Ensure ai_message_2 is also correctly handled
                            ai_message_2 = "\n".join(
                                content["text"] if isinstance(content, dict) and "text" in content else str(content)
                                for content in message.content
                            )
                        else:
                            ai_message_2 = message.content
                            
            # Remove <answer> and </answer> from AI messages
            def clean_ai_message(message):
                if message:
                    return re.sub(r"</?answer>", "", message).strip()
                return None

            ai_message_1 = clean_ai_message(ai_message_1)
            ai_message_2 = clean_ai_message(ai_message_2)

            # Convert tool_message into a list by splitting at 'Source: {}\nContent:' or '\n\nSource: {}\nContent:'
            tool_message_list = []
            if tool_message:
                tool_message_list = re.split(r"\n?\n?Source: {}\nContent:\s*", tool_message.strip())
                tool_message_list = [msg.strip() for msg in tool_message_list if msg.strip()]

            data = {
                "human_message": human_message,
                "ai_message_1": ai_message_1,
                "tool_message": tool_message_list,  
                "ai_message_2": ai_message_2
            }

        
            return Response({
                "status": 200,
                "message": "Chat generated successfully",
                "data": data
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
            