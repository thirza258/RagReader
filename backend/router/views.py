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
from common.constant import (
    CONFIG_VARIANTS,
    DEFAULT_ANALYSIS_CONFIG,
    DEFAULT_POOL_TOP_N,
    DEFAULT_TOP_K,
    GROUND_TRUTH_MODES,
    LLM_MODELS,
    POOL_TOP_N_MAX,
    POOL_TOP_N_MIN,
    RETRIEVAL_METHODS,
    TOP_K_MAX,
    TOP_K_MIN,
    build_variants,
    normalize_analysis_config,
)
from common.schema import get_responses


class InsertDataView(GenericAPIView):
    serializer_class = InsertDataSerializer
    parser_classes = [MultiPartParser, FormParser]

    def create_document(self, data: dict, user: GuestUser) -> Document:
        return Document.objects.create(
            user=user,
            name=data["filename"],
            source_type=data.get("source_type", "pdf"),
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

        except GuestUser.DoesNotExist:
            return get_responses().response_404(error="User not found")
        except ValueError as e:
            return get_responses().response_400(error=str(e))
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

class AnalysisConfigView(APIView):
    """The option set the Deep Analysis sidebar renders.

    Served rather than hardcoded in the frontend so the model list can never
    drift from the models the backend actually knows how to instantiate.
    """

    def get(self, request):
        return Response({
            "retrieval_methods": RETRIEVAL_METHODS,
            "models": LLM_MODELS,
            "ground_truth_modes": GROUND_TRUTH_MODES,
            "top_k": {"min": TOP_K_MIN, "max": TOP_K_MAX, "default": DEFAULT_TOP_K},
            "pool_top_n": {
                "min": POOL_TOP_N_MIN,
                "max": POOL_TOP_N_MAX,
                "default": DEFAULT_POOL_TOP_N,
            },
            "defaults": DEFAULT_ANALYSIS_CONFIG,
            "max_variants": len(CONFIG_VARIANTS),
        }, status=status.HTTP_200_OK)


class StartAnalysisView(GenericAPIView):
    def create_analysis_batch(
        self,
        user: GuestUser,
        conversation: Conversation,
        query: str,
        job_id: str,
        config: dict,
        total_variants: int,
    ) -> AnalysisBatch:
        batch = AnalysisBatch.objects.create(
            user=user,
            conversation=conversation,
            query=query,
            job_id=job_id,
            total_variants=total_variants,
            config=config,
        )
        return batch

    def describe_ground_truth(self, conversation: Conversation) -> dict:
        """Summarise the ground-truth chunk set backing this conversation."""
        from evaluation.models import GroundTruthChunk

        chunks = list(
            GroundTruthChunk.objects
            .filter(conversation=conversation)
            .values_list("source", flat=True)
        )
        return {
            "count": len(chunks),
            "source": chunks[0] if chunks else None,
        }

    def post(self, request):
        try:
            conversation_id = request.data.get("conversation_id")

            current_conversation = Conversation.objects.get(id=conversation_id)
            username = current_conversation.user.username
            query = current_conversation.query

            document_id = current_conversation.document.pk if current_conversation.document else None

            # Which method × model variants to run, and how deep to retrieve.
            # Absent or partial input falls back to the full matrix.
            config = normalize_analysis_config(request.data.get("config"))
            variants = build_variants(config)

            batch_id = str(uuid.uuid4())

            cache.set(f"job_input_{batch_id}", {
                "username": username,
                "query": query,
                "document_id": document_id,
                "conversation_id": conversation_id,
                "config": config,
            }, timeout=300)

            analysis_batch = self.create_analysis_batch(
                current_conversation.user,
                current_conversation,
                query,
                job_id=batch_id,
                config=config,
                total_variants=len(variants),
            )
            current_batch = analysis_batch.job_id

            response = {
                "message": "Analysis initiated",
                "batch_id": current_batch,
                "document_id" : document_id,
                "query": query,
                "config": config,
                "expected_count": len(variants),
                # What the retrieval metrics will actually be scored against.
                # Surfaced so the UI can flag "you asked for pooling but the
                # stored ground truth is still your manual selection".
                "ground_truth": self.describe_ground_truth(current_conversation),
            }

            return Response(response, status=status.HTTP_202_ACCEPTED)

        except Conversation.DoesNotExist:
            return Response({"error": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AnalysisStatusView(GenericAPIView):
    # The URL captures this as <job_id>; the name must match or every request
    # raises TypeError before the view body runs.
    def get(self, request, job_id):
        try:
            batch_id = uuid.UUID(job_id)
            analysis_batch = AnalysisBatch.objects.get(job_id=batch_id)

            results = AnalysisResult.objects.filter(batch=analysis_batch)
            data = []
            for result in results:
                eval_dict = {}
                if isinstance(result.evaluation_metrics, dict):
                    eval_dict = result.evaluation_metrics
                elif isinstance(result.evaluation_metrics, list):
                    for m in result.evaluation_metrics:
                        if isinstance(m, dict) and "name" in m and "value" in m:
                            eval_dict[m["name"]] = m["value"]
                        elif isinstance(m, dict):
                            eval_dict.update(m)

                chunks = [
                    {
                        "chunk_id": chunk.get("id") or chunk.get("chunk_id"),
                        "text": chunk.get("text", ""),
                        "score": chunk.get("score")
                    }
                    for chunk in (result.retrieved_chunks or [])
                ]

                data.append({
                    "batch_id": str(batch_id),
                    "method": result.method,
                    "aiModel": result.ai_model,
                    "query": result.query,
                    "answer": result.answer,
                    "context": chunks,
                    "retrievedChunks": chunks,
                    "evaluation": eval_dict,
                    "progress": 100,
                    "result": result.answer,
                })

            total_expected = analysis_batch.total_variants or len(data)
            is_complete = len(data) >= total_expected if total_expected > 0 else len(data) > 0
            progress = int((len(data) / total_expected) * 100) if total_expected > 0 else 100

            response_payload = {
                "batch_id": str(batch_id),
                "progress": progress,
                "is_complete": is_complete,
                "total": total_expected,
                "completed": len(data),
                "results": data,
                "data": data 
            }

            return Response(response_payload, status=status.HTTP_200_OK)
        except AnalysisBatch.DoesNotExist:
            return Response({"error": "Analysis batch not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)