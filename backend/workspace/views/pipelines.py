"""Retrieval pipelines and their immutable versions (PRD §17–19, §33)."""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response

from workspace.errors import ApiError
from workspace.models import Pipeline
from workspace.serializers import (
    PipelineCreateInput, PipelinePatchInput, pipeline_payload, validated, version_payload,
)
from workspace.services import pipelines
from workspace.views.base import OwnedAPIView

TAGS = ["Pipelines"]
WORKSPACE_PARAM = OpenApiParameter("workspace_id", OpenApiTypes.INT, description="Defaults to the user's default workspace.")


def _payload(pipeline):
    return pipeline_payload(pipeline, pipelines.latest_version(pipeline))


class PipelineListView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="pipelines_list", summary="A workspace's pipelines, default first (creates the default on first use)", parameters=[WORKSPACE_PARAM], responses=OpenApiTypes.OBJECT)
    def get(self, request):
        workspace = self.resolve_workspace(request.query_params.get("workspace_id"))
        pipelines.default_pipeline_for(workspace)
        rows = Pipeline.objects.filter(workspace=workspace).order_by("-is_default", "created_at", "id")
        return Response({"results": [_payload(pipeline) for pipeline in rows]})

    @extend_schema(tags=TAGS, operation_id="pipelines_create", summary="Create a pipeline (version 1 = the defaults plus `config`)", request=PipelineCreateInput, responses={201: OpenApiTypes.OBJECT})
    def post(self, request):
        values = validated(PipelineCreateInput, request.data)
        workspace = self.resolve_workspace(values.get("workspace_id"))
        name = pipelines.clean_name(values["name"], required=True)
        pipeline, version = pipelines.create_pipeline(workspace, name, values.get("config"))
        return Response(pipeline_payload(pipeline, version), status=201)


class PipelineOptionsView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="pipelines_options", summary="Strategies, fusion methods, rerankers, models, ranges and defaults for the pipeline form", responses=OpenApiTypes.OBJECT)
    def get(self, request):
        return Response(pipelines.options())


class PipelineDetailView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="pipelines_retrieve", summary="A pipeline with its latest version", responses=OpenApiTypes.OBJECT)
    def get(self, request, pipeline_id):
        return Response(_payload(self.get_pipeline(pipeline_id)))

    @extend_schema(tags=TAGS, operation_id="pipelines_partial_update", summary="Rename a pipeline or change its settings (a changed configuration adds a version)", request=PipelinePatchInput, responses=OpenApiTypes.OBJECT)
    def patch(self, request, pipeline_id):
        pipeline = self.get_pipeline(pipeline_id)
        values = validated(PipelinePatchInput, request.data)
        name = pipelines.clean_name(values["name"], required=True) if "name" in values else None
        pipeline, version, created = pipelines.update_pipeline(pipeline, name=name, changes=values.get("config"))
        return Response({**pipeline_payload(pipeline, version), "version_created": created})

    @extend_schema(tags=TAGS, operation_id="pipelines_destroy", summary="Delete a pipeline (not the default); its conversations switch to the default", responses={204: None})
    def delete(self, request, pipeline_id):
        pipeline = self.get_pipeline(pipeline_id)
        if pipeline.is_default:
            raise ApiError("default_pipeline", "The workspace's default pipeline cannot be deleted.", status=409)
        pipeline.delete()
        return Response(status=204)


class PipelineVersionsView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="pipelines_versions_list", summary="Every version of a pipeline, newest first", responses=OpenApiTypes.OBJECT)
    def get(self, request, pipeline_id):
        pipeline = self.get_pipeline(pipeline_id)
        pipelines.latest_version(pipeline)
        versions = pipeline.versions.order_by("-number")
        return Response({"pipeline_id": pipeline.pk, "results": [version_payload(version) for version in versions]})
