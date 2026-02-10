import uuid

from django.shortcuts import render
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
    AnalysisBatch, AnalysisResult
)
from router.models import Job
from router.tasks import initialize_rag_task, run_single_analysis

from rag.rag_service import rag_registry
from router.serializers import (InsertDataSerializer, 
InsertTextSerializer, 
InsertURLSerializer, 
QuerySerializer, )
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
    def post(self, request):
        try:
            username = request.data.get("USER")
            user = GuestUser.objects.get(username=username) 

            job = Job.objects.create(
                user=user,
                status=Job.Status.PENDING,
                progress=0
            )

            method = CONFIG_VARIANTS[0]["method"]
            model_config = CONFIG_VARIANTS[0]["model"]
            
            transaction.on_commit(lambda: initialize_rag_task.delay(
                job_id=str(job.id),
                username=username,
                method=method,
                model_config=model_config
            ))
            
            return get_responses().response_202(message={
                "job_id": job.id,
                "status": "PENDING",      
                "progress": 0,
                "username": username
            })

        except Exception as e:
            return get_responses().response_500(error=str(e))

class JobStatusView(APIView):
    def get(self, request, job_id):
        try:
            job = Job.objects.get(id=job_id)
            return get_responses().response_200(response={
                "job_id": job.id,
                "status": job.status,      
                "progress": job.progress,
                "username": job.user.username,
                "error": job.error_message,
                "updated_at": job.updated_at
            })
        except Job.DoesNotExist:
            return get_responses().response_404(error="Job not found")
        except Exception as e:
            return get_responses().response_500(error=str(e))

class QueryView(GenericAPIView):
    serializer_class = QuerySerializer

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

            answer = rag_registry.get_engine(CONFIG_VARIANTS[0]["method"], CONFIG_VARIANTS[0]["model"]).run(username, query)
            return get_responses().response_200(response=answer)
        except Exception as e:
            return get_responses().response_500(error=str(e))


class StartAnalysisView(GenericAPIView):
    def post(self, request):
        try:
            username = request.data.get("USER")
            query = request.data.get("QUERY")
            
            batch_id = str(uuid.uuid4())
            
            cache.set(f"job_input_{batch_id}", {
                "username": username,
                "query": query
            }, timeout=300)
            
            analysis_batch = AnalysisBatch.objects.create(
                user=GuestUser.objects.get(username=username),
                query=query,
                job_id=batch_id,
                total_variants=len(CONFIG_VARIANTS)
            )
            analysis_batch.save()

            response = {
                "message": "Analysis initiated",
                "batch_id": batch_id,
                "expected_count": len(CONFIG_VARIANTS)
            }
            
            return Response(response, status=status.HTTP_202_ACCEPTED)
            
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AnalysisStatusView(GenericAPIView):
    def get(self, request, batch_id):
        # 1. Simulate DB Lookup
        try:
            batch_id = uuid.UUID(batch_id)
            analysis_batch = AnalysisBatch.objects.get(job_id=batch_id)

            results = AnalysisResult.objects.filter(batch=analysis_batch)
            data = [{
                "method": result.method,
                "result": result.result_data
            } for result in results]

            progress = 100.0 
            is_complete = True

            response_payload = {
                "batch_id": batch_id,
                "progress": progress,
                "is_complete": is_complete,
                "data": data 
            }

            # mimicking your get_responses().response_200
            return Response(response_payload, status=status.HTTP_200_OK)
        
        except AnalysisBatch.DoesNotExist:
            return Response({"error": "Analysis batch not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)