from django.shortcuts import render
from rest_framework.views import APIView
from backend.utils.helper import _document_base_path, conversation_id_generator
from backend.router.models import Document, DocumentVector, VectorStore, Conversation, ConversationHistory, GuestUser
from backend.router import response, data_loader
from backend.rag.rag_service import rag_registry

# Create your views here.
class InsertDataView(APIView):

    def create_document(self, data: dict, user: GuestUser) -> Document:
        return Document.objects.create(
            user=user,
            name=data["filename"],
            source_type="pdf",
            source_path=data["source_path"],
            extracted_text_path=data["text_path"],
        )

    def post(self, request):
        try:
            username = request.data["USER"]
            file = request.FILES["FILE"]

            user = GuestUser.objects.get(username=username)

            data = data_loader.process_input(file, username)

            document = self.create_document(data, user)

            return response.response_200("Data inserted successfully!")

        except Exception as e:
            return response.response_500(error=str(e))

class InsertURLView(APIView):

    def create_document(self, data: dict) -> Document:
        user = GuestUser.objects.get(email=data["user"])
        document = Document.objects.create(
            user=user,
            name=data["name"],
            source_type=data["source_path"],
            source_url=data["source_url"],
        )
        return document

    def post(self, request):
        try:
            data = data_loader.process_input(request.data["URL"])
            user = request.data["USER"]
            base_path = _document_base_path(user)
            document = self.create_document(data, base_path)
            document.save()
            return response.response_200("Data inserted successfully!")
        except Exception as e:
            return response.response_500(error=str(e))

class OpenChatView(APIView):
    def post(self, request):
        try: 
            username = request.data["USER"]
            rag_registry.get_engine("Dense Retrieval", "gpt-4o-mini").init(username)
            
            return response.response_200("Chat initialized successfully!")
        except Exception as e:
            return response.response_500(error=str(e))

class QueryView(APIView):
    def post(self, request):
        try:
            username = request.data["USER"]
            query = request.data["QUERY"]
            answer = rag_registry.get_engine("Dense Retrieval", "gpt-4o-mini").run(username, query)
            return response.response_200(response=answer)
        except Exception as e:
            return response.response_500(error=str(e))