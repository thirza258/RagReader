from django.shortcuts import render
from rest_framework.views import APIView
from utils.helper import _document_base_path, conversation_id_generator
from router.models import Document, DocumentVector, VectorStore, Conversation, ConversationHistory, GuestUser
from utils.insert_file import get_loader
from rag.rag_service import rag_registry
from router.serializers import InsertDataSerializer, InsertTextSerializer, InsertURLSerializer, QuerySerializer, SignUpSerializer
from common.constant import CONFIG_VARIANTS
from rest_framework.generics import GenericAPIView
from common.schema import get_responses
from django.db import IntegrityError
from rest_framework.parsers import MultiPartParser, FormParser


class InsertDataView(GenericAPIView):
    serializer_class = InsertDataSerializer
    parser_classes = [MultiPartParser, FormParser]

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
            print(request.data)
            print(request.FILES)
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            username = serializer.validated_data["USER"]
            file = serializer.validated_data["FILE"]

            user = GuestUser.objects.get(username=username)
            data = get_loader().process_input(file, username)

            document = self.create_document(data, user)
            document.save()

            return get_responses().response_200("Data inserted successfully!")

        except Exception as e:
            return get_responses().response_500(error=str(e))

class InsertURLView(GenericAPIView):
    serializer_class = InsertURLSerializer

    def create_document(self, data: dict) -> Document:
        user = GuestUser.objects.get(username=data["user"])
        document = Document.objects.create(
            user=user,
            name=data["name"],
            source_type=data["source_type"],
            extracted_text_path=data["text_path"],
            source_path=data["source_path"],
        )
        return document

    def post(self, request):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            username = serializer.validated_data["USER"]
            url = serializer.validated_data["URL"]

            data = get_loader().process_input(url, username)
            document = self.create_document(data)
            document.save()

            return get_responses().response_200("Data inserted successfully!")
        except Exception as e:
            return get_responses().response_500(error=str(e))

class InsertTextView(GenericAPIView):
    serializer_class = InsertTextSerializer

    def create_document(self, data: dict) -> Document:
        user = GuestUser.objects.get(username=data.get("user"))
        document = Document.objects.create(
            user=user,
            name=data.get("name"),
            source_type="text",
            extracted_text_path=data.get("text_path"),
            source_path=data.get("source_path"),
        )
        return document

    def post(self, request):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            username = serializer.validated_data.get("USER")
            text = serializer.validated_data.get("TEXT")

            data = get_loader().process_input(text, username)
            document = self.create_document(data)
            document.save()

            return get_responses().response_200("Data inserted successfully!")
        except Exception as e:
            return get_responses().response_500(error=str(e))

class OpenChatView(APIView):
    def post(self, request):
        # try: 
            username = request.data["USER"]
            rag_registry.get_engine(CONFIG_VARIANTS[0]["method"], CONFIG_VARIANTS[0]["model"]).init(username)
            
            return get_responses().response_200("Chat initialized successfully!")
        # except Exception as e:
        #     return get_responses().response_500(error=str(e))

class QueryView(GenericAPIView):
    serializer_class = QuerySerializer

    def post(self, request):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            username = serializer.validated_data["USER"]
            query = serializer.validated_data["QUERY"]
            
            answer = rag_registry.get_engine(CONFIG_VARIANTS[0]["method"], CONFIG_VARIANTS[0]["model"]).run(username, query)
            return get_responses().response_200(response=answer)
        except Exception as e:
            return get_responses().response_500(error=str(e))

class SignUpView(GenericAPIView):
    serializer_class = SignUpSerializer

    def post(self, request):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            try:
                GuestUser.objects.create(
                    email=serializer.validated_data["EMAIL"],
                    username=serializer.validated_data["USERNAME"],
                )
            except IntegrityError:
                return get_responses().response_400("User already exists")
            return get_responses().response_201("User created successfully!")
        except Exception as e:
            return get_responses().response_500(error=str(e))