from django.urls import path
from .views import (
    InsertDataView,
    DenseRAGPipelineView,
    GraphRAGPipelineView,
    HybridRAGPipelineView,
    SparseRAGPipelineView,
    VoteDataView,
)

urlpatterns = [
    path("insert-data/", InsertDataView.as_view(), name="insert-data"),
    path("dense-rag/", DenseRAGPipelineView.as_view(), name="dense-rag"),
    path("graph-rag/", GraphRAGPipelineView.as_view(), name="graph-rag"),
    path("hybrid-rag/", HybridRAGPipelineView.as_view(), name="hybrid-rag"),
    path("sparse-rag/", SparseRAGPipelineView.as_view(), name="sparse-rag"),
    path("vote-data/", VoteDataView.as_view(), name="vote-data"),
]