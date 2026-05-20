import uuid

from django.db import transaction
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser

from utils.insert_file import get_loader
from router.models import (
    Document, 
    GuestUser, Job,
    AnalysisBatch, AnalysisResult, 
    Conversation, ConversationHistory
)
from router.tasks import initialize_rag_task

from rag.rag_service import rag_registry
from router.serializers import (
    InsertDataSerializer, 
    InsertTextSerializer, 
    InsertURLSerializer, 
    QuerySerializer 
)
from common.constant import CONFIG_VARIANTS
from common.schema import get_responses


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
    def response_adjuster(self, job):
        return {
            "job_id" : job.pk,
            "status" : "PENDING",
            "progress" : 0,
            "username": job.user.username
        }
        
    def create_job(self, user: GuestUser) -> Job:
        job = Job.objects.create(
            user=user,
            status=Job.Status.PENDING,
            progress=0,
            document=Document.objects.filter(user=user).order_by('-created_at').first()
        )
        return job

    def post(self, request):
        try:
            username = request.data.get("USER")
            user = GuestUser.objects.get(username=username) 

            job = self.create_job(user)

            method = CONFIG_VARIANTS[0]["method"]
            model_config = CONFIG_VARIANTS[0]["model"]
            
            transaction.on_commit(lambda: initialize_rag_task.delay(
                job_id=str(job.id),
                username=username,
                method=method,
                model_config=model_config
            ))
            
            return get_responses().response_202(message=self.response_adjuster(job))

        except Exception as e:
            return get_responses().response_500(error=str(e))
        
class DocumentView(APIView):
    def get(self, request, username):
        try:
            user = GuestUser.objects.filter(username=username).first()
            if not user:
                return get_responses().response_404(error="User not found")
            
            document = Document.objects.filter(user=user).last()
            if not document:
                return get_responses().response_404(error="Document not found for user")
            
            data = {
                "id": document.pk,
                "name": document.name,
                "source_type": document.source_type,
                "source_path": document.source_path,
                "extracted_text_path": document.extracted_text_path[:100],
                "created_at": document.created_at
            }
            return get_responses().response_200(response=data)
        except Exception as e:
            return get_responses().response_500(error=str(e))

class JobStatusView(APIView):
    def responses_adjuster(self, job):
        return {
            "job_id": job.id,
            "status": job.status,      
            "progress": job.progress,
            "username": job.user.username,
            "error": job.error_message,
            "updated_at": job.updated_at
        }
    
    def get(self, request, job_id):
        try:
            job = Job.objects.get(id=job_id)
            return get_responses().response_200(response=self.responses_adjuster(job))
        except Job.DoesNotExist:
            return get_responses().response_404(error="Job not found")
        except Exception as e:
            return get_responses().response_500(error=str(e))

class ConversationView(GenericAPIView):
    def get(self, request, conversation_id):
        try:
            conversation = Conversation.objects.get(id=conversation_id)
            data = {
                "id": conversation.pk,
                "document_id": conversation.document.pk if conversation.document else None,
                "query": conversation.query,
                "response": conversation.response,
                "context": conversation.context,
                "created_at": conversation.created_at
            }
            return get_responses().response_200(response=data)
        except Conversation.DoesNotExist:
            return get_responses().response_404(error="Conversation not found")
        except Exception as e:
            return get_responses().response_500(error=str(e))
  
class ConversationHistoryView(GenericAPIView):
    def get(self, request, username):
        try:
            user = GuestUser.objects.get(username=username)
            conversation_histories = ConversationHistory.objects.filter(user=user).select_related('conversation').order_by('-created_at')
            data = [{
                "query": history.conversation.query,
                "response": history.conversation.response,
                "created_at": history.created_at
            } for history in conversation_histories]
            return get_responses().response_200(response=data)
        except GuestUser.DoesNotExist:
            return get_responses().response_404(error="User not found")
        except Exception as e:
            return get_responses().response_500(error=str(e))

class QueryView(GenericAPIView):
    serializer_class = QuerySerializer
    
    def save_conversation(self, username: str, query: str, answer: str, context: str, document: Document ) -> Conversation:
        user = GuestUser.objects.get(username=username)
        
        conversation = Conversation.objects.create(
            user=user,
            document=document,
            query=query,
            response=answer,
            context=context
        )
        ConversationHistory.objects.create(
            user=user,
            conversation=conversation
        )
        return conversation

    def post(self, request):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            username = serializer.validated_data["USER"]
            query = serializer.validated_data["QUERY"]
            
            last_job = Job.objects.filter(user__username=username).order_by('-created_at').first()
            
            if not last_job:
                 return get_responses().response_404(error="No initialization job found. Please upload a document first.")

            if last_job.status != Job.Status.READY:
                 return get_responses().response_400(error=f"System is still initializing. Current status: {last_job.status}")
            
            document = last_job.document
            document_id = document.pk if document else None
            
            answer = rag_registry.get_engine(CONFIG_VARIANTS[0]["method"], CONFIG_VARIANTS[0]["model"]).run(username, query)
            
            retrieved_chunks = answer.get("context", [])
            llm_answer = answer.get("answer", "")
            
            context_str = "\n\n".join(doc["text"] for doc in retrieved_chunks)
            answer_record = self.save_conversation(username, query, llm_answer, context_str, document)
            
            answer["conversation_id"] = answer_record.pk
            answer["document_id"] = document_id
            
            return get_responses().response_200(response=answer)
        except Exception as e:
            return get_responses().response_500(error=str(e))

class StartAnalysisView(GenericAPIView):
    def create_analysis_batch(self, user: GuestUser, conversation: Conversation, query: str, job_id: str) -> AnalysisBatch:
        batch = AnalysisBatch.objects.create(
            user=user,
            conversation=conversation,
            query=query,
            job_id=job_id,
            total_variants=len(CONFIG_VARIANTS)
        )
        return batch
    
    def post(self, request):
        try:
            conversation_id = request.data.get("conversation_id")
            
            current_conversation = Conversation.objects.get(id=conversation_id)
            username = current_conversation.user.username
            query = current_conversation.query
            
            document_id = current_conversation.document.pk if current_conversation.document else None
            print(document_id)
            batch_id = str(uuid.uuid4())
            
            cache.set(f"job_input_{batch_id}", {
                "username": username,
                "query": query,
                "document_id": document_id,
                "conversation_id": conversation_id
            }, timeout=300)
            
            candidate_pooling = None
            analysis_batch = self.create_analysis_batch(current_conversation.user, current_conversation, query, job_id=batch_id)
            current_batch = analysis_batch.job_id
            
            response = {
                "message": "Analysis initiated",
                "batch_id": current_batch,
                "document_id" : document_id,
                "query": query,
                "expected_count": len(CONFIG_VARIANTS)
            }
            
            return Response(response, status=status.HTTP_202_ACCEPTED)
            
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AnalysisStatusView(GenericAPIView):
    def get(self, request, batch_id):
        try:
            batch_id = uuid.UUID(batch_id)
            analysis_batch = AnalysisBatch.objects.get(job_id=batch_id)

            results = AnalysisResult.objects.filter(batch=analysis_batch)
            data = [{
                "method": result.method,
                "result": result.answer
            } for result in results]

            progress = 100.0 
            is_complete = True

            response_payload = {
                "batch_id": batch_id,
                "progress": progress,
                "is_complete": is_complete,
                "data": data 
            }

            return Response(response_payload, status=status.HTTP_200_OK)
        except AnalysisBatch.DoesNotExist:
            return Response({"error": "Analysis batch not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)