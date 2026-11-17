"""Research tasks API (PRD §22–25, §47). Token required; another user's task is 404."""
import json

from django.http import HttpResponse
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.response import Response

from research import serializers
from research.models import ResearchTask
from research.services import engine, runner
from workspace.errors import ApiError, error_object
from workspace.views.base import OwnedAPIView, parse_id


class ResearchView(OwnedAPIView):
    def get_task(self, task_id):
        pk = parse_id(task_id)
        task = (ResearchTask.objects.select_related("workspace", "workspace__user")
                .filter(pk=pk, workspace__user=self.request.user).first() if pk else None)
        if task is None:
            raise ApiError("not_found", "Research task not found.", status=404)
        return task


def _queued(task, status):
    """202 normally; 503 with the task when its worker could not be reached."""
    if task.status == ResearchTask.Status.FAILED and task.error_code == "job_queue_unavailable":
        return Response({"error": error_object(task.error_code, task.error_message, retryable=True),
                         "task": serializers.task_payload(task)}, status=503)
    return Response(serializers.task_payload(task), status=status)


class ResearchOptionsView(ResearchView):
    def get(self, request):
        return Response({
            "kinds": [{"id": value, "label": label} for value, label in ResearchTask.Kind.choices],
            "default_dimensions": engine.DEFAULT_DIMENSIONS,
            "field_types": list(engine.FIELD_TYPES),
            "limits": {key: list(value) if isinstance(value, tuple) else value for key, value in runner.LIMITS.items()},
            "verdicts": list(engine.VERDICTS), "confidence": list(engine.CONFIDENCE),
            "max_evidence": engine.MAX_EVIDENCE,
        })


class ResearchTaskListView(ResearchView):
    def get(self, request):
        workspace = self.resolve_workspace(request.query_params.get("workspace_id"))
        tasks = ResearchTask.objects.filter(workspace=workspace)
        kind, status = request.query_params.get("kind"), request.query_params.get("status")
        if kind:
            if kind not in ResearchTask.Kind.values:
                raise runner.invalid({"kind": [f"Choose one of {', '.join(ResearchTask.Kind.values)}."]})
            tasks = tasks.filter(kind=kind)
        if status:
            if status not in ResearchTask.Status.values:
                raise runner.invalid({"status": [f"Choose one of {', '.join(ResearchTask.Status.values)}."]})
            tasks = tasks.filter(status=status)
        rows = [runner.expire_if_stalled(task) for task in tasks.order_by("-created_at", "-id")[:100]]
        return Response({"results": [serializers.task_payload(task, full=False) for task in rows]})

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        workspace = self.resolve_workspace(data.get("workspace_id"))
        task = runner.create_task(request.user, workspace, data)
        return _queued(task, 202)


class ResearchTaskDetailView(ResearchView):
    def get(self, request, task_id):
        return Response(serializers.task_payload(runner.expire_if_stalled(self.get_task(task_id))))

    def patch(self, request, task_id):
        task = self.get_task(task_id)
        data = request.data if isinstance(request.data, dict) else {}
        errors, changes = {}, {}
        if "title" in data:
            title = runner._text(data, "title", runner.LIMITS["title"], errors, required=True)
            if title:
                changes["title"] = title
        if "notes" in data:
            changes["notes"] = runner._text(data, "notes", runner.LIMITS["notes"], errors, required=False) or ""
        if errors:
            raise runner.invalid(errors)
        if changes:
            # Only these columns: a running worker owns the rest of the row.
            ResearchTask.objects.filter(pk=task.pk).update(**changes)
            task.refresh_from_db()
        return Response(serializers.task_payload(task))

    def delete(self, request, task_id):
        runner.delete_task(self.get_task(task_id))
        return Response(status=204)


class ResearchTaskCancelView(ResearchView):
    def post(self, request, task_id):
        return Response(serializers.task_payload(runner.cancel_task(self.get_task(task_id))))


class ResearchTaskRetryView(ResearchView):
    def post(self, request, task_id):
        return _queued(runner.retry_task(self.get_task(task_id)), 202)


class _FormatIsAFileType(DefaultContentNegotiation):
    """`?format=md` names the export's file type, not a DRF renderer."""

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type


class ResearchTaskExportView(ResearchView):
    content_negotiation_class = _FormatIsAFileType

    def get(self, request, task_id):
        task = self.get_task(task_id)
        fmt = (request.query_params.get("format") or "md").lower()
        if fmt not in ("md", "json"):
            raise runner.invalid({"format": ["Choose md or json."]})
        if fmt == "md":
            response = HttpResponse(runner.to_markdown(task), content_type="text/markdown; charset=utf-8")
        else:
            response = HttpResponse(json.dumps(serializers.task_payload(task), ensure_ascii=False, indent=2, default=str),
                                    content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="research-{task.pk}.{fmt}"'
        response["X-Content-Type-Options"] = "nosniff"
        return response
