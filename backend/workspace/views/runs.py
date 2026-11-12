"""Retrieval runs: the trace behind every answer and the workspace's reliability (PRD §21, §32, §49)."""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response

from evaluation.models import Chunk
from workspace.models import RetrievalRun
from workspace.serializers import RunListQuery, RunSummaryQuery, run_detail_payload, run_payload, validated
from workspace.services.runs import reliability_summary
from workspace.views.base import OwnedAPIView

TAGS = ["Retrieval runs"]
WORKSPACE_PARAM = OpenApiParameter("workspace_id", OpenApiTypes.INT, description="Defaults to the user's default workspace (or the conversation's, when conversation_id is given).")
LIST_PARAMS = [
    WORKSPACE_PARAM,
    OpenApiParameter("conversation_id", OpenApiTypes.INT),
    OpenApiParameter("status", OpenApiTypes.STR, enum=RetrievalRun.Status.values),
    OpenApiParameter("source", OpenApiTypes.STR, enum=RetrievalRun.Source.values),
    OpenApiParameter("limit", OpenApiTypes.INT, description="1–200, default 50."),
]
SUMMARY_PARAMS = [
    WORKSPACE_PARAM,
    OpenApiParameter("days", OpenApiTypes.INT, description="1–365, default 30."),
    OpenApiParameter("source", OpenApiTypes.STR, enum=RetrievalRun.Source.values),
]


class RetrievalRunListView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="retrieval_runs_list", summary="Recent runs, newest first", parameters=LIST_PARAMS, responses=OpenApiTypes.OBJECT)
    def get(self, request):
        values = validated(RunListQuery, request.query_params)
        params = request.query_params
        runs = RetrievalRun.objects.filter(user=request.user)
        conversation_id = params.get("conversation_id")
        if conversation_id not in (None, ""):
            runs = runs.filter(conversation=self.get_session(conversation_id))
        if params.get("workspace_id") not in (None, "") or conversation_id in (None, ""):
            runs = runs.filter(workspace=self.resolve_workspace(params.get("workspace_id")))
        if values.get("status"):
            runs = runs.filter(status=values["status"])
        if values.get("source"):
            runs = runs.filter(source=values["source"])
        limit = values["limit"]
        rows = list(runs.order_by("-started_at", "-id")[:limit + 1])
        return Response({"results": [run_payload(run) for run in rows[:limit]], "has_more": len(rows) > limit})


class RetrievalRunDetailView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="retrieval_runs_retrieve", summary="One run's full trace: provenance, spans and candidates", responses=OpenApiTypes.OBJECT)
    def get(self, request, run_id):
        run = self.get_run(run_id)
        spans = list(run.spans.order_by("ordinal"))
        candidates = list(run.candidates.select_related("document").order_by("rank"))
        # Whole passages for the reader, while the chunk still exists in the
        # same (owned) document; otherwise the stored snippet is returned.
        wanted = {candidate.chunk_id for candidate in candidates if candidate.chunk_id is not None and candidate.document_id}
        chunks = {
            pk: (document_id, text)
            for pk, document_id, text in Chunk.objects.filter(pk__in=wanted, document__user=request.user)
            .values_list("pk", "document_id", "text")
        } if wanted else {}
        texts = {}
        for candidate in candidates:
            found = chunks.get(candidate.chunk_id)
            if found is not None and found[0] == candidate.document_id:
                texts[candidate.pk] = found[1]
        return Response(run_detail_payload(run, spans, candidates, texts))


class RetrievalRunSummaryView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="retrieval_runs_summary", summary="Reliability of a workspace: failure rates, latency percentiles, tokens, ingestion", parameters=SUMMARY_PARAMS, responses=OpenApiTypes.OBJECT)
    def get(self, request):
        values = validated(RunSummaryQuery, request.query_params)
        workspace = self.resolve_workspace(request.query_params.get("workspace_id"))
        return Response(reliability_summary(request.user, workspace, days=values["days"], source=values.get("source")))
