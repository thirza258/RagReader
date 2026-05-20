from django.urls import path
from .views import (
    ChunkView, 
    CreateGroundTruthChunk, 
    CreateGroundTruthResponse,
    GroundTruthChunkEvaluationView,
    GroundTruthResponseEvaluationView,
    GetGroundTruthChunk
)

urlpatterns = [
    path('chunk/', ChunkView.as_view(), name='chunk-create'),
    path('chunk/<int:document_id>/', ChunkView.as_view(), name='chunk-get'),
    path('ground-truth-chunk/', CreateGroundTruthChunk.as_view(), name='create_ground_truth_chunk'),
    path('ground-truth-chunk/<int:conversation_id>/', GetGroundTruthChunk.as_view(), name='get_ground_truth_chunk'),
    path('ground-truth-response/', CreateGroundTruthResponse.as_view(), name='create_ground_truth_response'),
    path('ground-truth-response/<int:conversation_id>/', CreateGroundTruthResponse.as_view(), name='get_ground_truth_response'),
    path('evaluate/ground-truth-chunk/', GroundTruthChunkEvaluationView.as_view(), name='evaluate_ground_truth_chunk'),
    path('evaluate/ground-truth-response/', GroundTruthResponseEvaluationView.as_view(), name='evaluate_ground_truth_response'),
]
         