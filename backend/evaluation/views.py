from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Chunk, GroundTruthChunk, GroundTruthResponse
from router.models import Conversation, GuestUser, Document
from common.chunker import DocumentChunker
from common.schema import get_responses

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
            username = request.data.get("username")
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
            chunks = chunker.chunk(document.text)
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
            conversation_id = request.data.get("conversation_id")
            chunk_id = request.data.get("chunk_id")
            
            conversation = Conversation.objects.get(id=conversation_id)
            chunk = Chunk.objects.get(id=chunk_id)
            
            GroundTruthChunk.objects.create(conversation=conversation, chunk=chunk)
            return get_responses().response_200("Ground Truth Chunk Created")
        except Conversation.DoesNotExist:
            return Response({"error": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND)
        except Chunk.DoesNotExist:
            return Response({"error": "Chunk not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error creating GroundTruthChunk: {e}")
            return Response({"error": "Failed to create Ground Truth Chunk"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
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
        

