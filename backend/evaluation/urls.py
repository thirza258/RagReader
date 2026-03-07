from django.urls import path
from .views import ChunkView, CreateGroundTruthChunk, CreateGroundTruthResponse

urlpatterns = [
    path('chunk/', ChunkView.as_view(), name='chunk'),
    path('ground_truth_chunk/', CreateGroundTruthChunk.as_view(), name='create_ground_truth_chunk'),
    path('ground_truth_response/', CreateGroundTruthResponse.as_view(), name='create_ground_truth_response'),
]
         