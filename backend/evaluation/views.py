from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from evaluation.models import Chunk, GroundTruthChunk, GroundTruthResponse
from router.models import Conversation, GuestUser, Document, AnalysisBatch, AnalysisResult
from common.chunker import DocumentChunker
from common.schema import get_responses
from .eval import evaluate_chunks, evaluate_response

from utils.insert_file import DataLoader

import logging

logger = logging.getLogger(__name__)

class ChunkView(APIView):
    def get_document(self, username: str) -> Document | None:
        try:
            user = GuestUser.objects.filter(username=username).first()
            if not user:
                return None
            return Document.objects.filter(user=user).last()
        except Exception as e:
            logger.error(f"Error getting document for {username}: {e}")
            return None
        
    def create_chunk(self, document: Document, chunks, metadata: dict) -> Chunk:
        try:
            for chunk_text in chunks:
                chunk = Chunk.objects.create(document=document, text=chunk_text, metadata=metadata)
            return chunk
        except Exception as e:
            logger.error(f"Error creating chunk for document {document.id}: {e}")
            return None
        
    def post(self, request):
        try:
            username = request.data.get("USER")
            document = self.get_document(username)
            if not document:
                return Response({"error": "Document not found for user"}, status=status.HTTP_404_NOT_FOUND)
            
            config = {
                "chunk_strategy": "fixed",
                "chunk_size": 500,
                "overlap": 50,
                "embedding_client": None
            }
            
            document = self.get_document(username)
            chunker = DocumentChunker(
                strategy=config["chunk_strategy"],
                chunk_size=config["chunk_size"],
                overlap=config["overlap"],
                embedding_client=config["embedding_client"]
            )
            loader = DataLoader()
            extracted_text = loader.load(document.extracted_text_path)
            chunks = chunker.chunk(extracted_text)
            if not chunks:
                return Response({"error": "Failed to chunk document"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            if not document:
                return Response({"error": "Document not found for user"}, status=status.HTTP_404_NOT_FOUND)
            self.create_chunk(document, chunks, metadata=config)
            
            return get_responses().response_200("Chunk Created")
        except Document.DoesNotExist:
            return Response({"error": "Document not found"}, status=status.HTTP_404_NOT_FOUND)

    def get(self, request, document_id):
        try:
            chunks = Chunk.objects.filter(document_id=document_id)
            chunk_data = [{"id": chunk.id, "text": chunk.text, "metadata": chunk.metadata} for chunk in chunks]
            return Response({"chunks": chunk_data}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error retrieving chunks for document {document_id}: {e}")
            return Response({"error": "Failed to retrieve chunks"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CreateGroundTruthChunk(APIView):
    def post(self, request):
        try:
            conversation_id = int(str(request.data.get("conversation_id")).strip())
            chunk_ids = request.data.get("chunk_id", [])

            if not isinstance(chunk_ids, list):
                chunk_ids = [chunk_ids]

            conversation = Conversation.objects.filter(id=conversation_id).first()
            if not conversation:
                return Response({"error": "Conversation not found"}, status=404)

            chunks = Chunk.objects.filter(id__in=chunk_ids)

            if not chunks.exists():
                return Response({"error": "Chunks not found"}, status=404)

            GroundTruthChunk.objects.bulk_create([
                GroundTruthChunk(conversation=conversation, chunk=chunk)
                for chunk in chunks
            ])

            return get_responses().response_200("Ground Truth Chunk Created")

        except Exception as e:
            logger.error(f"Error creating GroundTruthChunk: {e}")
            return Response({"error": "Failed to create Ground Truth Chunk"}, status=500)
        
class GetGroundTruthChunk(APIView):
    def get(self, request, conversation_id):
        try:
            gt_chunks = GroundTruthChunk.objects.filter(conversation_id=conversation_id)
            gt_chunk_data = [{"id": gt_chunk.id, "chunk_id": gt_chunk.chunk_id} for gt_chunk in gt_chunks]
            return Response({"ground_truth_chunks": gt_chunk_data}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error retrieving GroundTruthChunks for conversation {conversation_id}: {e}")
            return Response({"error": "Failed to retrieve Ground Truth Chunks"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class CreateGroundTruthResponse(APIView):
    def post(self, request):
        try:
            conversation_id = request.data.get("conversation_id")
            response_text = request.data.get("response")
            metadata = request.data.get("metadata", {})
            
            conversation = Conversation.objects.get(id=conversation_id)
            
            GroundTruthResponse.objects.create(conversation=conversation, response=response_text, metadata=metadata)
            return get_responses().response_200("Ground Truth Response Created")
        except Conversation.DoesNotExist:
            return Response({"error": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error creating GroundTruthResponse: {e}")
            return Response({"error": "Failed to create Ground Truth Response"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
    def get(self, request, conversation_id):
        try:
            gt_responses = GroundTruthResponse.objects.filter(conversation_id=conversation_id)
            gt_response_data = [{"id": gt_response.id, "response": gt_response.response, "metadata": gt_response.metadata} for gt_response in gt_responses]
            return Response({"ground_truth_responses": gt_response_data}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error retrieving GroundTruthResponses for conversation {conversation_id}: {e}")
            return Response({"error": "Failed to retrieve Ground Truth Responses"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class GroundTruthChunkEvaluationView(APIView):
    def update_evaluation_metrics(self, conversation: Conversation, new_metrics: dict):
        try:
            current_conversation = Conversation.objects.get(id=conversation.id)
            existing_metrics = current_conversation.evaluation_metrics or {}
            existing_metrics.update(new_metrics)
            
            conversation.save()
        except Exception as e:
            logger.error(f"Error updating evaluation metrics for conversation {conversation.id}: {e}")
            
    def post(self, request):
        try:
            conversation_id = request.data.get("conversation_id")
            batch_id = request.data.get("batch_id")

            if not conversation_id or not batch_id:
                return Response(
                    {"error": "conversation_id and batch_id are required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            conversation = Conversation.objects.get(id=conversation_id)
            
            # Ground truth chunk IDs for this conversation
            gt_chunk_ids = list(
                GroundTruthChunk.objects
                .filter(conversation=conversation)
                .values_list("chunk_id", flat=True)
            )

            if not gt_chunk_ids:
                return Response(
                    {"error": "No ground truth chunks found for this conversation"},
                    status=status.HTTP_404_NOT_FOUND
                )

            logger.info(f"GT chunk IDs: {gt_chunk_ids}")

            results = AnalysisResult.objects.filter(batch__job_id=batch_id)
            if not results.exists():
                return Response(
                    {"error": "No results found for this batch"},
                    status=status.HTTP_404_NOT_FOUND
                )

            evaluations = []
            for result in results:
                retrieved_chunk_ids = [
                    chunk["id"]
                    for chunk in (result.retrieved_chunks or [])
                    if chunk.get("id") is not None
                ]

                logger.info(
                    f"Evaluating method={result.method} model={result.ai_model} "
                    f"retrieved={retrieved_chunk_ids}"
                )

                scores = evaluate_chunks(retrieved_chunk_ids, gt_chunk_ids)

                existing_metrics = result.evaluation_metrics or []
                existing_metrics.append({
                    "name": "ground_truth_eval",
                    "retrieved_chunk_ids": retrieved_chunk_ids,
                    "gt_chunk_ids": gt_chunk_ids,
                    "scores": scores
                })
                result.evaluation_metrics = existing_metrics
                result.save(update_fields=["evaluation_metrics"])

                evaluations.append({
                    "method": result.method,
                    "ai_model": result.ai_model,
                    "retrieved_chunk_ids": retrieved_chunk_ids,
                    "gt_chunk_ids": gt_chunk_ids,
                    "scores": scores
                })

            return Response({"evaluations": evaluations}, status=status.HTTP_200_OK)

        except Conversation.DoesNotExist:
            return Response({"error": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error evaluating Ground Truth: {e}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class GroundTruthResponseEvaluationView(APIView):
    def post(self, request):
        try:
            conversation_id = request.data.get("conversation_id")
            response_text = request.data.get("response")

            if not conversation_id or not response_text:
                return Response(
                    {"error": "conversation_id and response are required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            conversation = Conversation.objects.get(id=conversation_id)
            ground_truth = GroundTruthResponse.objects.filter(conversation=conversation).first()

            if not ground_truth:
                return Response(
                    {"error": "No ground truth response found for this conversation"},
                    status=status.HTTP_404_NOT_FOUND
                )

            scores = evaluate_response(response_text, ground_truth.response)

            return Response(
                {
                    "conversation_id": conversation.id,
                    "scores": scores,
                },
                status=status.HTTP_200_OK
            )
        except Conversation.DoesNotExist:
            return Response({"error": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error evaluating Ground Truth Response: {e}")
            return Response({"error": "Failed to evaluate Ground Truth Response"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
