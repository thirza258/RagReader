import uuid
import logging
import time
from functools import wraps

from common.errors import PipelineError, error_payload

from django.db import transaction, OperationalError, connection
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.exceptions import ValidationError

from utils.insert_file import get_loader
from router.models import (
    Document, 
    GuestUser, Job,
    AnalysisBatch, AnalysisResult, 
    Conversation, ConversationHistory
)
from router.tasks import initialize_rag_task

from rag.rag_service import apply_retrieval_depth, engine_execution, rag_registry
from router.serializers import (
    InsertDataSerializer, 
    InsertTextSerializer, 
    InsertURLSerializer, 
    QuerySerializer 
)
from ai_handler.model_catalog import fetch_catalog
from common.analysis_modules import MODULE_COMPATIBILITY, RAG_MODULES
from router.analysis import batch_snapshot, has_completed_analysis
from common.constant import (
    CHILD_TOP_K_MAX,
    CHILD_TOP_K_MIN,
    DEFAULT_ANALYSIS_CONFIG,
    DEFAULT_CHAT_VARIANT,
    DEFAULT_CHILD_TOP_K,
    DEFAULT_JUDGE_MODEL,
    DEFAULT_POOL_TOP_N,
    DEFAULT_RRF_K,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_K,
    GROUND_TRUTH_MODES,
    INGEST_CONFIG,
    MAX_VARIANTS,
    MODEL_IDS,
    POOL_TOP_N_MAX,
    POOL_TOP_N_MIN,
    RERANKER_MODELS,
    RETRIEVAL_METHODS,
    RRF_K_MAX,
    RRF_K_MIN,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
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

def public_error_response(exc, *, code="request_failed", message="The request could not be completed. Try again."):
    if isinstance(exc, ValidationError):
        return Response({"error": "The request contains invalid or missing fields.", "error_code": "invalid_request",
                         "retryable": False, "details": exc.detail}, status=400)
    if not isinstance(exc, PipelineError):
        logging.getLogger(__name__).error("Request failed", exc_info=exc)
    payload = error_payload(exc, code=code, message=message)
    http_status = getattr(exc, "http_status", 500)
    return Response({**payload, "status": http_status, "message": payload["error"], "data": None}, status=http_status)


def retry_locked_request(function):
    """SQLite lacks row locks; retry a competing job insert after rollback."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        for attempt in range(4):
            try:
                return function(*args, **kwargs)
            except OperationalError as exc:
                if connection.vendor != "sqlite" or "locked" not in str(exc).lower():
                    return public_error_response(exc)
                if attempt < 3:
                    time.sleep(0.1 * (attempt + 1))
        return public_error_response(PipelineError("database_busy", "The job database is busy. Try again shortly; an accepted job keeps its ID.", retryable=True, http_status=503))
    return wrapped


def job_payload(job):
    return {"job_id": str(job.pk), "document_id": job.document_id, "status": job.status,
            "progress": job.progress, "username": job.user.username,
            "error": job.error_message, "error_code": job.error_code,
            "retryable": job.retryable, "updated_at": job.updated_at}


class OpenChatView(APIView):
    @retry_locked_request
    def post(self, request):
        try:
            username = request.data.get("USER")
            if not isinstance(username, str) or not username.strip():
                raise PipelineError("invalid_user", "A username is required to initialize a document.", http_status=400)
            queue_failure = []
            with transaction.atomic():
                # Serialize double-clicks, retries and reloads for this user.
                user = GuestUser.objects.select_for_update().get(username=username)
                document = Document.objects.filter(user=user).order_by("-created_at").first()
                if not document:
                    raise PipelineError("missing_document", "Upload a document before opening chat.", http_status=404)
                job = Job.objects.filter(user=user, document=document).order_by("-created_at").first()
                if job:
                    job.expire_if_stalled()
                created = job is None or (job.status == Job.Status.FAILED and request.data.get("retry") is True)
                if created:
                    job = Job.objects.create(user=user, document=document)
                    def enqueue():
                        try:
                            initialize_rag_task.delay(job_id=str(job.pk), username=user.username,
                                method=DEFAULT_CHAT_VARIANT["method"], model_config=DEFAULT_CHAT_VARIANT["model"])
                        except Exception:
                            failure = PipelineError("job_queue_unavailable", "The initialization worker could not be reached. Try again shortly.", retryable=True, http_status=503)
                            job.mark_failed(str(failure), failure.code, failure.retryable)
                            queue_failure.append(failure)
                            logging.getLogger(__name__).warning("Could not enqueue initialization job %s", job.pk, exc_info=True)
                    transaction.on_commit(enqueue)
            if queue_failure:
                payload = error_payload(queue_failure[0])
                return Response({**payload, "job_id": str(job.pk), "data": job_payload(job)}, status=503)
            return Response({"status": 202 if created else 200, "message": "Document initialization", "data": job_payload(job)}, status=202 if created else 200)
        except GuestUser.DoesNotExist:
            return public_error_response(PipelineError("user_not_found", "User not found.", http_status=404))
        except OperationalError:
            raise
        except Exception as exc:
            return public_error_response(exc)

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
    def get(self, request, job_id):
        try:
            try:
                canonical = uuid.UUID(job_id)
            except (ValueError, TypeError, AttributeError):
                raise PipelineError("invalid_job_id", "Job ID must be a valid UUID.", http_status=400)
            job = Job.objects.select_related("user").get(pk=canonical)
            job.expire_if_stalled()
            return get_responses().response_200(response=job_payload(job))
        except Job.DoesNotExist:
            return public_error_response(PipelineError("job_not_found", "Initialization job not found. Upload a document or restart initialization.", http_status=404))
        except Exception as exc:
            return public_error_response(exc)

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
                raise PipelineError("job_not_found", "No initialization job found. Please upload a document first.", http_status=404)
            last_job.expire_if_stalled()

            if last_job.status == Job.Status.FAILED:
                raise PipelineError(last_job.error_code or "initialization_failed", last_job.error_message or "Document initialization failed. Retry initialization.", retryable=last_job.retryable, http_status=409)

            if last_job.status != Job.Status.READY:
                raise PipelineError("job_not_ready", f"Document initialization is {last_job.status.lower()}. Wait for initialization to finish.", retryable=True, http_status=409)
            
            document = last_job.document
            if document is None or document.user_id != last_job.user_id:
                raise PipelineError("missing_document", "This job no longer has a valid document. Upload a document and initialize it again.", http_status=409)
            document_id = document.pk if document else None
            
            engine = rag_registry.get_engine(
                DEFAULT_CHAT_VARIANT["method"], DEFAULT_CHAT_VARIANT["model"]
            )

            # Engines are process-wide singletons, and both deep analysis and
            # candidate pooling re-depth them (up to TOP_K_MAX / POOL_TOP_N_MAX).
            # Without this, plain chat keeps whichever depth the last of those
            # left behind instead of DEFAULT_TOP_K.
            with engine_execution(engine):
                apply_retrieval_depth(engine, DEFAULT_TOP_K)
                answer = engine.run(username, query, document_id=document_id)
            
            retrieved_chunks = answer.get("context", [])
            llm_answer = answer.get("answer", "")
            
            context_str = "\n\n".join(doc["text"] for doc in retrieved_chunks)
            answer_record = self.save_conversation(username, query, llm_answer, context_str, document)
            
            answer["conversation_id"] = answer_record.pk
            answer["document_id"] = document_id
            
            return get_responses().response_200(response=answer)
        except Exception as exc:
            return public_error_response(exc)

class AnalysisConfigView(APIView):
    """The option set the Deep Analysis sidebar renders.

    Served rather than hardcoded in the frontend so the ranges, the defaults
    and the model catalogue can never drift from what the backend will accept.

    `models` is the live OpenRouter catalogue when it can be reached and the
    three shipped defaults otherwise; `model_catalog.source` says which, so the
    UI can be honest about it. Any well-formed OpenRouter id is runnable
    whether or not it appears in this list.
    """

    def get(self, request):
        catalog = fetch_catalog(force=request.query_params.get("refresh") == "1")

        return Response({
            "retrieval_methods": RETRIEVAL_METHODS,
            "modules": RAG_MODULES,
            "module_compatibility": MODULE_COMPATIBILITY,
            "models": catalog["models"],
            "default_models": MODEL_IDS,
            "model_catalog": {
                "source": catalog["source"],
                "count": len(catalog["models"]),
                "error": catalog["error"],
            },
            "rerankers": RERANKER_MODELS,
            "ground_truth_modes": GROUND_TRUTH_MODES,
            "top_k": {"min": TOP_K_MIN, "max": TOP_K_MAX, "default": DEFAULT_TOP_K},
            "pool_top_n": {
                "min": POOL_TOP_N_MIN,
                "max": POOL_TOP_N_MAX,
                "default": DEFAULT_POOL_TOP_N,
            },
            "temperature": {
                "min": TEMPERATURE_MIN,
                "max": TEMPERATURE_MAX,
                "default": DEFAULT_TEMPERATURE,
            },
            "child_top_k": {
                "min": CHILD_TOP_K_MIN,
                "max": CHILD_TOP_K_MAX,
                "default": DEFAULT_CHILD_TOP_K,
            },
            "rrf_k": {"min": RRF_K_MIN, "max": RRF_K_MAX, "default": DEFAULT_RRF_K},
            "judge_model": {"default": DEFAULT_JUDGE_MODEL},
            # Applied once at ingest and therefore read-only here: the stored
            # index is only meaningful against the settings that built it.
            # See common/constant.py for the full reasoning.
            "ingest": INGEST_CONFIG,
            "defaults": DEFAULT_ANALYSIS_CONFIG,
            "max_variants": MAX_VARIANTS,
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
            if isinstance(conversation_id, bool) or not str(conversation_id or "").isdigit():
                raise PipelineError("invalid_conversation_id", "A valid conversation ID is required.", http_status=400)
            conversation = Conversation.objects.select_related("user", "document").get(pk=conversation_id)
            if not conversation.user or not conversation.document:
                raise PipelineError("missing_document", "This conversation has no document. Upload a document and start a new conversation.", http_status=400)
            if conversation.document.user_id != conversation.user_id:
                raise PipelineError("document_mismatch", "The conversation and document belong to different users.", http_status=400)
            config = normalize_analysis_config(request.data.get("config"))
            modules_available = has_completed_analysis(conversation.pk)
            if config["modules"] and not modules_available:
                raise PipelineError("baseline_required", "Complete the first deep analysis before enabling RAG modules.", http_status=400)
            request_id = request.data.get("request_id")
            try:
                batch_id = uuid.UUID(str(request_id)) if request_id is not None else uuid.uuid4()
            except (ValueError, TypeError, AttributeError):
                raise PipelineError("invalid_request_id", "Analysis request ID must be a valid UUID.", http_status=400)
            batch, created = AnalysisBatch.objects.get_or_create(job_id=batch_id, defaults={
                "user": conversation.user, "conversation": conversation, "query": conversation.query,
                "config": config, "total_variants": len(build_variants(config)),
            })
            if batch.conversation_id != conversation.pk or normalize_analysis_config(batch.config) != config:
                raise PipelineError("request_id_conflict", "This request ID belongs to a different analysis. Use a new request ID for a new run.", http_status=409)
            # No cache write is needed to recover a job: the DB holds its inputs.
            return Response({"message": "Analysis initiated" if created else "Analysis resumed",
                "batch_id": str(batch.job_id), "document_id": conversation.document_id,
                "query": batch.query, "config": config, "expected_count": len(build_variants(config)),
                "modules_available": modules_available, "ground_truth": self.describe_ground_truth(conversation),
            }, status=status.HTTP_202_ACCEPTED)
        except Conversation.DoesNotExist:
            return public_error_response(PipelineError("conversation_not_found", "Conversation not found.", http_status=404))
        except Exception as exc:
            return public_error_response(exc)

class AnalysisStatusView(GenericAPIView):
    def get(self, request, job_id):
        try:
            try:
                canonical = uuid.UUID(job_id)
            except (ValueError, TypeError, AttributeError):
                raise PipelineError("invalid_job_id", "Analysis job ID must be a valid UUID.", http_status=400)
            batch = AnalysisBatch.objects.select_related("conversation").get(job_id=canonical)
            conversation_id = request.query_params.get("conversation_id")
            if conversation_id is not None and str(batch.conversation_id) != conversation_id:
                raise PipelineError("job_conversation_mismatch", "This job belongs to a different conversation. Start a new analysis for this conversation.", http_status=409)
            payload = batch_snapshot(batch)
            # REST uses complete result objects, including persisted failures.
            for result in payload["results"]:
                result.setdefault("retrievedChunks", [])
                if result.get("error"):
                    result["answer"] = "Error: " + result["error"]
            payload.update({"document_id": batch.conversation.document_id if batch.conversation else None,
                            "conversation_id": batch.conversation_id,
                            "modules_available": has_completed_analysis(batch.conversation_id), "data": payload["results"]})
            return Response(payload)
        except AnalysisBatch.DoesNotExist:
            return public_error_response(PipelineError("job_not_found", "Analysis batch not found. Start a new analysis.", http_status=404))
        except Exception as exc:
            return public_error_response(exc)
