from django.db import transaction
from django.db.models import Count
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from workspace.errors import ApiError
from workspace.models import Workspace, default_workspace_for
from workspace.serializers import WorkspaceInput, validated, workspace_payload
from workspace.services.documents import delete_documents
from workspace.views.base import OwnedAPIView

TAGS = ["Workspaces"]


def annotated(queryset):
    return queryset.annotate(
        document_count=Count("documents", distinct=True),
        conversation_count=Count("conversations", distinct=True),
    )


class WorkspaceListView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="workspaces_list", summary="List workspaces (creates the default one on first use)", responses=OpenApiTypes.OBJECT)
    def get(self, request):
        default_workspace_for(request.user)
        workspaces = annotated(Workspace.objects.filter(user=request.user)).order_by("-is_default", "created_at", "id")
        return Response({"results": [workspace_payload(workspace) for workspace in workspaces]})

    @extend_schema(tags=TAGS, operation_id="workspaces_create", summary="Create a workspace", request=WorkspaceInput, responses={201: OpenApiTypes.OBJECT})
    def post(self, request):
        data = validated(WorkspaceInput, request.data)
        with transaction.atomic():
            first = not Workspace.objects.filter(user=request.user).exists()
            workspace = Workspace.objects.create(user=request.user, name=data["name"].strip(), is_default=first)
        return Response(workspace_payload(workspace, 0, 0), status=201)


class WorkspaceDetailView(OwnedAPIView):
    def _payload(self, workspace):
        return workspace_payload(annotated(Workspace.objects.filter(pk=workspace.pk)).get())

    @extend_schema(tags=TAGS, operation_id="workspaces_retrieve", summary="Get a workspace", responses=OpenApiTypes.OBJECT)
    def get(self, request, workspace_id):
        return Response(self._payload(self.get_workspace(workspace_id)))

    @extend_schema(tags=TAGS, operation_id="workspaces_partial_update", summary="Rename a workspace", request=WorkspaceInput, responses=OpenApiTypes.OBJECT)
    def patch(self, request, workspace_id):
        workspace = self.get_workspace(workspace_id)
        data = validated(WorkspaceInput, request.data)
        workspace.name = data["name"].strip()
        workspace.save(update_fields=["name", "updated_at"])
        return Response(self._payload(workspace))

    @extend_schema(tags=TAGS, operation_id="workspaces_destroy", summary="Delete a workspace with its documents and conversations", responses={204: None})
    def delete(self, request, workspace_id):
        workspace = self.get_workspace(workspace_id)
        with transaction.atomic():
            others = Workspace.objects.select_for_update().filter(user=request.user).exclude(pk=workspace.pk)
            successor = others.order_by("created_at", "id").first()
            if successor is None:
                raise ApiError("last_workspace", "You cannot delete your only workspace.", status=409)
            # Files and index pickles are not rows: remove them explicitly
            # (after commit) before the cascade forgets where they were.
            delete_documents(workspace.documents.all())
            was_default = workspace.is_default
            workspace.delete()
            if was_default:
                Workspace.objects.filter(pk=successor.pk).update(is_default=True)
        return Response(status=204)
