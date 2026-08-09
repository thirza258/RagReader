from django.db import transaction
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from evaluation.models import Chunk, GroundTruthChunk, GroundTruthResponse
from router.models import Conversation, GuestUser, Document, AnalysisBatch, AnalysisResult
from common.chunker import DocumentChunker
from common.constant import DEFAULT_POOL_TOP_N, POOL_TOP_N_MAX
from common.schema import get_responses
from .candidate_pooler import DEFAULT_RRF_K, build_default_pooler
from .eval import evaluate_chunks, evaluate_response

from utils.insert_file import DataLoader

import logging

logger = logging.getLogger(__name__)


def _positive_int(value, default: int, maximum: int | None = None) -> int:
    """Coerce a request field to a positive int, falling back to `default`."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum) if maximum is not None else parsed

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

            # The selection replaces the conversation's ground truth outright —
            # re-submitting (or switching back from candidate pooling) must not
            # leave the previous set behind.
            with transaction.atomic():
                GroundTruthChunk.objects.filter(conversation=conversation).delete()
                GroundTruthChunk.objects.bulk_create([
                    GroundTruthChunk(
                        conversation=conversation,
                        chunk=chunk,
                        source=GroundTruthChunk.Source.MANUAL,
                    )
                    for chunk in chunks
                ])

            return get_responses().response_200("Ground Truth Chunk Created")

        except Exception as e:
            logger.error(f"Error creating GroundTruthChunk: {e}")
            return Response({"error": "Failed to create Ground Truth Chunk"}, status=500)

class GetGroundTruthChunk(APIView):
    def get(self, request, conversation_id):
        try:
            gt_chunks = (
                GroundTruthChunk.objects
                .filter(conversation_id=conversation_id)
                .select_related("chunk")
            )
            gt_chunk_data = [{
                "id": gt_chunk.id,
                "chunk_id": gt_chunk.chunk_id,
                "text": gt_chunk.chunk.text,
                "source": gt_chunk.source,
                "rank": gt_chunk.rank,
                "rrf_score": gt_chunk.rrf_score,
                "sources": (gt_chunk.metadata or {}).get("sources", []),
            } for gt_chunk in gt_chunks]
            return Response(
                {
                    "ground_truth_chunks": gt_chunk_data,
                    # One conversation has one ground-truth set, so the mode is
                    # whatever produced it.
                    "source": gt_chunk_data[0]["source"] if gt_chunk_data else None,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"Error retrieving GroundTruthChunks for conversation {conversation_id}: {e}")
            return Response({"error": "Failed to retrieve Ground Truth Chunks"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CandidatePoolView(APIView):
    """Derive the ground-truth chunk set by pooling every retrieval method.

    Runs the conversation's query through Dense, Sparse and Hybrid retrieval,
    fuses the three ranked lists with Reciprocal Rank Fusion, and stores the
    top-N as `source="pooled"` ground truth. The alternative — the user
    hand-picking chunks — writes the same rows with `source="manual"`, so
    everything downstream (`run_analysis`, Precision@K/Recall@K/F1@K) is
    unchanged either way.
    """

    def _resolve_username(self, conversation: Conversation) -> str | None:
        if conversation.user:
            return conversation.user.username
        if conversation.document and conversation.document.user:
            return conversation.document.user.username
        return None

    def _persist(self, conversation: Conversation, pooled) -> list[dict]:
        """Replace the conversation's ground truth with the pooled ranking."""
        chunk_ids = pooled.rrf_chunk_ids
        chunks_by_id = Chunk.objects.in_bulk(chunk_ids)

        rows, payload = [], []
        for rank, chunk_dict in enumerate(pooled.rrf_ranked_chunks, start=1):
            chunk = chunks_by_id.get(chunk_dict.get("chunk_id"))
            if chunk is None:
                # The index can outlive a re-chunk; skip ids with no DB row.
                logger.warning(f"Pooled chunk {chunk_dict.get('chunk_id')} has no Chunk row — skipped.")
                continue

            sources = chunk_dict.get("sources", [])
            rows.append(GroundTruthChunk(
                conversation=conversation,
                chunk=chunk,
                source=GroundTruthChunk.Source.POOLED,
                rank=rank,
                rrf_score=chunk_dict.get("rrf_score"),
                metadata={"sources": sources},
            ))
            payload.append({
                "chunk_id": chunk.id,
                "text": chunk.text,
                "rank": rank,
                "rrf_score": chunk_dict.get("rrf_score"),
                "sources": sources,
            })

        with transaction.atomic():
            GroundTruthChunk.objects.filter(conversation=conversation).delete()
            GroundTruthChunk.objects.bulk_create(rows)

        return payload

    def post(self, request):
        conversation_id = request.data.get("conversation_id")
        if not conversation_id:
            return Response(
                {"error": "conversation_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            conversation = Conversation.objects.get(id=conversation_id)
        except (Conversation.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND)

        # Same ceiling normalize_analysis_config applies, so a direct API call
        # and the sidebar agree on this field's bounds.
        top_n = _positive_int(request.data.get("top_n"), DEFAULT_POOL_TOP_N, POOL_TOP_N_MAX)
        rrf_k = _positive_int(request.data.get("rrf_k"), DEFAULT_RRF_K)

        pooler = build_default_pooler(k=rrf_k, top_n=top_n)
        if not pooler.pipeline_names:
            return Response(
                {"error": "No retrieval engines are available for pooling."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            pooled = pooler.pool(
                query=conversation.query,
                username=self._resolve_username(conversation),
            )
        except Exception as e:
            logger.error(f"Candidate pooling failed for conversation {conversation_id}: {e}", exc_info=True)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not pooled.rrf_ranked_chunks:
            # Never wipe a ground-truth set the user already has just because
            # every retriever came back empty — report why instead.
            return Response(
                {
                    "error": "Candidate pooling returned no chunks. Existing ground truth was left untouched.",
                    "pipelines": [
                        {"name": name, "retrieved": len(r.ranked_chunks), "error": r.error}
                        for name, r in pooled.per_pipeline.items()
                    ],
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        chunks = self._persist(conversation, pooled)

        return Response({
            "conversation_id": conversation.id,
            "source": GroundTruthChunk.Source.POOLED,
            "query": pooled.query,
            "optimized_query": pooled.optimized_query,
            "rrf_k": rrf_k,
            "top_n": top_n,
            "pipelines": [
                {
                    "name": name,
                    "retrieved": len(result.ranked_chunks),
                    "error": result.error,
                }
                for name, result in pooled.per_pipeline.items()
            ],
            "chunks": chunks,
        }, status=status.HTTP_200_OK)
        
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
