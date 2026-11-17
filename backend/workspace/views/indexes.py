"""Index versions: each document's built indexes (PRD §19, §33).

An index version is a `router.DocumentVector`: every ingestion or re-index
builds a new one and the document's `current_index` points at the one chat
searches. Building extra versions with other chunk settings is deferred (see
docs/prd-implementation.md, Phase 3).
"""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response

from router.models import DocumentVector
from workspace.serializers import index_version_payload
from workspace.views.base import OwnedAPIView

TAGS = ["Indexes"]
LIST_PARAMS = [
    OpenApiParameter("document_id", OpenApiTypes.INT, description="One document's index versions."),
    OpenApiParameter("workspace_id", OpenApiTypes.INT, description="Without document_id: every index of the workspace's documents (default workspace if omitted)."),
]


class IndexListView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="indexes_list", summary="Index versions, newest first", parameters=LIST_PARAMS, responses=OpenApiTypes.OBJECT)
    def get(self, request):
        document_id = request.query_params.get("document_id")
        if document_id not in (None, ""):
            vectors = DocumentVector.objects.filter(document=self.get_document(document_id))
        else:
            workspace = self.resolve_workspace(request.query_params.get("workspace_id"))
            vectors = DocumentVector.objects.filter(document__workspace=workspace, document__user=request.user)
        rows = vectors.select_related("document").order_by("-created_at", "-id")
        return Response({"results": [index_version_payload(vector, vector.document) for vector in rows]})


class IndexDetailView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="indexes_retrieve", summary="One index version", responses=OpenApiTypes.OBJECT)
    def get(self, request, index_id):
        vector = self.get_index(index_id)
        return Response(index_version_payload(vector, vector.document))
