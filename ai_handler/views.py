from django.shortcuts import render
import os
from langchain_openai import ChatOpenAI
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings
import bs4
from langchain import hub
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
from io import BytesIO
logger = logging.getLogger(__name__)

class ChatSystem:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        self.llm = None
        self.embeddings = None 
        self.vector_store = None
        self.graph = None
        self.vector_number = None
        
    def initialize_system(self, model_name, vector_number):
        self.llm = ChatOpenAI(model="gpt-4o-mini")
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
        
    def process_document(self, text_content):
        """
        Processes the given text content by splitting it into chunks and storing it in a vector database.

        Args:
            text_content (str): The text content to be processed.
        """
        self.vector_store = InMemoryVectorStore(self.embeddings)
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, 
            chunk_overlap=200
        )
        docs = text_splitter.split_text(text_content)
        self.vector_store.add_texts(docs)
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
            retrieved_docs = self.vector_store.similarity_search(query, k=5)
            serialized = "\n\n".join(
                f"Source: {doc.metadata}\nContent: {doc.page_content}"
                for doc in retrieved_docs
            )
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

                1. First, you will be given a set of document content in the following format:

                <docs_content>
                {docs_content}
                </docs_content>

                2. Carefully read and analyze the provided document content. This information will be the basis for answering the user's prompt.

                4. Your goal is to answer the prompt using only the information provided in the docs_content. Do not use any external knowledge or information that is not present in the given document content.

                5. Formulate your answer in Markdown format. Use appropriate Markdown syntax for headings, lists, emphasis, and any other formatting that would enhance the readability and structure of your response.

                6. Present your final answer within <answer> tags. The opening <answer> tag should be on its own line, followed by your Markdown-formatted response, and then the closing </answer> tag on its own line.

                7. Ensure that your answer is directly relevant to the prompt and based solely on the information provided in the docs_content. If the prompt asks for information that is not available in the given content, state that the information is not provided in the available documents.

                8. If appropriate, use quotes from the docs_content to support your answer. Format these quotes using Markdown syntax.

                Here's an example of how your response should be structured:

                <answer>

                # Main Topic

                ## Subtopic 1

                Information related to subtopic 1...

                ## Subtopic 2

                As stated in the document:

                > Relevant quote from the docs_content

                Further explanation...

                </answer>

                Remember, your entire response should be in Markdown format and enclosed within the <answer> tags.
                
                3. After processing the document content, below is the user prompt you need to answer:
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
        elif file_extension in [".txt", ".csv"]:
            try:
                return file_uploaded.read().decode("utf-8")
            except UnicodeDecodeError:
                # If UTF-8 fails, try ISO-8859-1
                file_uploaded.seek(0)
                try:
                    return file_uploaded.read().decode("ISO-8859-1")
                except UnicodeDecodeError as e:
                    raise Exception("File encoding is not supported")
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
            if "file" not in request.FILES:
                logger.error("No file found in the request.")
                return Response(
                    {"error": "No file found in the request"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            file_uploaded = request.FILES["file"]
            model_name = request.data["model_name"]
            vector_number = int(request.data["vector_number"])
            
            # Initialize the chat system
            print("Getting chat system instance...")
            chat_system = ChatSystem.get_instance()
            print("Initializing chat system...")
            chat_system.initialize_system(model_name, vector_number)
            print("Chat system initialized")
            
            # Save file
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
                print(all_text)
                # Process the document for chat system
                chat_system.process_document(all_text)
            except Exception as e:
                logger.error(f"Error processing file: {e}")
                return Response(
                    {"error": f"Error processing file: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Prepare the response data
            
            data = {
                "file": file_uploaded.name,
                "file_type": file_extension,
                "file_content": all_text,
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
            
import re
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)

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
                        ai_message_1 = message.content
                    elif isinstance(message, ToolMessage):
                        tool_message = message.content
                    elif isinstance(message, AIMessage):
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
                "tool_message": tool_message_list,  # Now a list
                "ai_message_2": ai_message_2
            }

            print(data)
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
