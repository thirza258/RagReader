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

# Create your views here.
llm = ChatOpenAI(model="gpt-4o-mini")
embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
vector_store = InMemoryVectorStore(embeddings)

# Load and chunk contents of the blog
loader = WebBaseLoader(
    web_paths=("https://lilianweng.github.io/posts/2023-06-23-agent/",),
    bs_kwargs=dict(
        parse_only=bs4.SoupStrainer(
            class_=("post-content", "post-title", "post-header")
        )
    ),
)
docs = loader.load()

text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
all_splits = text_splitter.split_documents(docs)

_ = vector_store.add_documents(documents=all_splits)

@tool(response_format="content_and_artifact")
def retrieve(query: str):
    """Retrieve information related to a query."""
    retrieved_docs = vector_store.similarity_search(query, k=5)
    serialized = "\n\n".join(
        (f"Source: {doc.metadata}\n" f"Content: {doc.page_content}")
        for doc in retrieved_docs
    )
    return serialized, retrieved_docs

graph_builder = StateGraph(MessagesState)

def query_or_respond(state: MessagesState):
    """Generate tool call for retrieval or respond."""
    llm_with_tools = llm.bind_tools([retrieve])
    response = llm_with_tools.invoke(state["messages"])
    # MessagesState appends messages to state instead of overwriting
    return {"messages": [response]}


# Step 2: Execute the retrieval.
tools = ToolNode([retrieve])


# Step 3: Generate a response using the retrieved content.
def generate(state: MessagesState):
    """Generate answer."""
    # Get generated ToolMessages
    recent_tool_messages = []
    for message in reversed(state["messages"]):
        if message.type == "tool":
            recent_tool_messages.append(message)
        else:
            break
    tool_messages = recent_tool_messages[::-1]

    # Format into prompt
    docs_content = "\n\n".join(doc.content for doc in tool_messages)
    system_message_content = (
        "You are an assistant for question-answering tasks. "
        "Use the following pieces of retrieved context to answer "
        "the question. If you don't know the answer, say that you "
        "don't know. Use three sentences maximum and keep the "
        "answer concise."
        "\n\n"
        f"{docs_content}"
    )
    conversation_messages = [
        message
        for message in state["messages"]
        if message.type in ("human", "system")
        or (message.type == "ai" and not message.tool_calls)
    ]
    prompt = [SystemMessage(system_message_content)] + conversation_messages

    # Run
    response = llm.invoke(prompt)
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

graph = graph_builder.compile()

input_message = "What is Task Decomposition?"

# Define variables to store messages
human_message = None
ai_message_1 = None
tool_message = None
ai_message_2 = None

for step in graph.stream(
    {"messages": [HumanMessage(content=input_message)]},
    stream_mode="values",
):
    messages = step["messages"]

    # Extract messages based on their class type
    for message in messages:
        if isinstance(message, HumanMessage):
            human_message = message.content
        elif isinstance(message, AIMessage) and ai_message_1 is None:
            ai_message_1 = message.content
        elif isinstance(message, ToolMessage):
            tool_message = message.content
        elif isinstance(message, AIMessage):
            ai_message_2 = message.content

# Print extracted messages
print("Human Message:", human_message)
print("AI Message 1:", ai_message_1)
print("Tool Message:", tool_message)
print("AI Message 2:", ai_message_2)

class GenerateChat(APIView):
    def post(self, request):
        try:
            input_message = request.data["input_message"]
            for step in graph.stream(
                {"messages": [HumanMessage(content=input_message)]},
                stream_mode="values",
            ):
                messages = step["messages"]

                # Extract messages based on their class type
                for message in messages:
                    if isinstance(message, HumanMessage):
                        human_message = message.content
                    elif isinstance(message, AIMessage) and ai_message_1 is None:
                        ai_message_1 = message.content
                    elif isinstance(message, ToolMessage):
                        tool_message = message.content
                    elif isinstance(message, AIMessage):
                        ai_message_2 = message.content
                
            data = {
                "human_message": human_message,
                "ai_message_1": ai_message_1,
                "tool_message": tool_message,
                "ai_message_2": ai_message_2
            }
            
            return Response({
                "status": 200,
                "message": "Chat generated successfully",
                "data": data
                }, status=status.HTTP_200_OK)
                        
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )


class FileSubmit(APIView):
    def post(self, request):
        try:
            file_uploaded = request.FILES["file"]
            file_extension = os.path.splitext(file_uploaded.name)[1].lower()
            if file_extension == ".pdf":
                # Handle PDF file
                # Add your PDF processing code here
                print("PDF file uploaded")
                pass
            elif file_extension == ".txt":
                # Handle TXT file
                # Add your TXT processing code here
                print("TXT file uploaded")
                pass
            elif file_extension == ".csv":
                # Handle CSV file
                # Add your CSV processing code here
                print("CSV file uploaded")
                pass
            else:
                return Response(
                    {"error": "Unsupported file type"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
                
            return Response(
                {"status": 200, "message": "File uploaded successfully"},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
            
