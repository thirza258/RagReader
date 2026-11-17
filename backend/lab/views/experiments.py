"""Experiments: registry, start/cancel/rerun, items, comparison (PRD §29–31, §42)."""
from rest_framework.response import Response

from lab import serializers
from lab.models import Experiment
from lab.services import comparison, runner
from lab.services import failures as failure_codes
from lab.views.base import LabView, invalid
from workspace.errors import ApiError, error_object
from workspace.views.base import parse_id

MAX_COMPARE = 6
ITEM_LIMIT_DEFAULT, ITEM_LIMIT_MAX = 100, 500


def _queue_failure(exc, status_ok):
    """503 with the experiment, or re-raise anything else."""
    experiment = getattr(exc, "experiment", None)
    if isinstance(exc, ApiError) and exc.code == "job_queue_unavailable" and experiment is not None:
        return Response({"error": error_object(exc.code, exc.message, retryable=True),
                         "experiment": serializers.experiment_payload(experiment)}, status=503)
    raise exc


class ExperimentListView(LabView):
    def get(self, request):
        params = request.query_params
        experiments = Experiment.objects.filter(workspace__user=request.user)
        if params.get("workspace_id") not in (None, "") or params.get("dataset_id") in (None, ""):
            experiments = experiments.filter(workspace=self.resolve_workspace(params.get("workspace_id")))
        if params.get("dataset_id") not in (None, ""):
            dataset = self.get_dataset(params.get("dataset_id"))
            experiments = experiments.filter(dataset_snapshot__dataset_id=dataset.pk)
        status = params.get("status")
        if status:
            if status not in Experiment.Status.values:
                raise invalid({"status": [f"Choose one of {', '.join(Experiment.Status.values)}."]})
            experiments = experiments.filter(status=status)
        rows = list(experiments.order_by("-created_at", "-id")[:200])
        for experiment in rows:
            runner.expire_if_stalled(experiment)
        return Response({"results": [serializers.experiment_payload(experiment) for experiment in rows]})

    def post(self, request):
        draft = isinstance(request.data, dict) and request.data.get("draft") is True
        try:
            experiment = runner.create_experiment(request.user, request.data)
        except ApiError as exc:
            return _queue_failure(exc, 202)
        return Response(serializers.experiment_payload(experiment), status=201 if draft else 202)


class ExperimentDetailView(LabView):
    def get(self, request, experiment_id):
        experiment = runner.expire_if_stalled(self.get_experiment(experiment_id))
        return Response(serializers.experiment_detail_payload(experiment))

    def patch(self, request, experiment_id):
        experiment = self.get_experiment(experiment_id)
        data = request.data if isinstance(request.data, dict) else {}
        errors = {}
        fields = []
        if "name" in data:
            name = runner.clean_text(data, "name", runner.MAX_NAME_CHARS, errors)
            if not name and "name" not in errors:
                errors["name"] = ["This field may not be blank."]
            experiment.name = name or experiment.name
            fields.append("name")
        for key, limit in (("hypothesis", runner.MAX_HYPOTHESIS_CHARS), ("conclusion", runner.MAX_CONCLUSION_CHARS)):
            if key in data:
                setattr(experiment, key, runner.clean_text(data, key, limit, errors))
                fields.append(key)
        if errors:
            raise invalid(errors)
        if fields:
            # Only these columns: a running worker owns the rest of the row.
            Experiment.objects.filter(pk=experiment.pk).update(**{field: getattr(experiment, field) for field in fields})
            experiment.refresh_from_db()
        return Response(serializers.experiment_detail_payload(experiment))

    def delete(self, request, experiment_id):
        runner.delete_experiment(self.get_experiment(experiment_id))
        return Response(status=204)


class ExperimentStartView(LabView):
    def post(self, request, experiment_id):
        experiment = self.get_experiment(experiment_id)
        try:
            experiment = runner.start_experiment(experiment)
        except ApiError as exc:
            return _queue_failure(exc, 202)
        return Response(serializers.experiment_payload(experiment), status=202)


class ExperimentCancelView(LabView):
    def post(self, request, experiment_id):
        experiment = runner.cancel_experiment(self.get_experiment(experiment_id))
        return Response(serializers.experiment_payload(experiment))


class ExperimentRerunView(LabView):
    def post(self, request, experiment_id):
        experiment = self.get_experiment(experiment_id)
        draft = isinstance(request.data, dict) and request.data.get("draft") is True
        try:
            copy = runner.rerun_experiment(experiment, request.data)
        except ApiError as exc:
            return _queue_failure(exc, 202)
        return Response(serializers.experiment_payload(copy), status=201 if draft else 202)


class ExperimentItemsView(LabView):
    def get(self, request, experiment_id):
        experiment = self.get_experiment(experiment_id)
        params = request.query_params
        errors = {}
        offset = parse_id(params.get("offset")) if params.get("offset") not in (None, "", "0") else 0
        limit = parse_id(params.get("limit")) if params.get("limit") not in (None, "") else ITEM_LIMIT_DEFAULT
        if offset is None:
            errors["offset"] = ["Expected a whole number ≥ 0."]
        if limit is None or not 1 <= limit <= ITEM_LIMIT_MAX:
            errors["limit"] = [f"Choose 1–{ITEM_LIMIT_MAX}."]
        status, category, label = params.get("status"), params.get("category"), params.get("label")
        if status and status not in ("pending", "completed", "failed"):
            errors["status"] = ["Choose pending, completed or failed."]
        if category and category not in failure_codes.CATEGORIES:
            errors["category"] = [f"Choose one of {', '.join(failure_codes.CATEGORIES)}."]
        if label and label not in failure_codes.CODES:
            errors["label"] = ["Unknown failure label."]
        if errors:
            raise invalid(errors)
        items = experiment.items.order_by("position")
        if status:
            items = items.filter(status=status)
        rows = list(items)
        if category or label:
            rows = [item for item in rows if any(
                (not category or entry.get("category") == category) and (not label or entry.get("code") == label)
                for entry in item.failure_labels or [])]
        from lab.services.datasets import DocumentResolver
        resolver = DocumentResolver(experiment.workspace)
        page = rows[offset:offset + limit]
        return Response({"results": [serializers.item_payload(item, resolver) for item in page],
                         "count": len(rows), "offset": offset, "limit": limit})


class ExperimentCompareView(LabView):
    def get(self, request):
        params = request.query_params
        raw = [part.strip() for part in (params.get("ids") or "").split(",") if part.strip()]
        ids = []
        for part in raw:
            pk = parse_id(part)
            if pk is None:
                raise invalid({"ids": ["Expected experiment ids separated by commas."]})
            if pk not in ids:
                ids.append(pk)
        if not 2 <= len(ids) <= MAX_COMPARE:
            raise invalid({"ids": [f"Compare 2–{MAX_COMPARE} different experiments."]})
        found = {experiment.pk: experiment for experiment in
                 Experiment.objects.select_related("workspace").filter(pk__in=ids, workspace__user=request.user)}
        if len(found) != len(ids):
            raise ApiError("not_found", "Experiment not found.", status=404)
        experiments = [runner.expire_if_stalled(found[pk]) for pk in ids]
        datasets = {(experiment.dataset_snapshot or {}).get("dataset_id") for experiment in experiments}
        if len(datasets) != 1:
            raise invalid({"ids": ["Experiments can only be compared on the same dataset."]})
        baseline_id = parse_id(params.get("baseline")) if params.get("baseline") not in (None, "") else ids[0]
        if baseline_id not in found:
            raise invalid({"baseline": ["The baseline must be one of the compared experiments."]})
        baseline = found[baseline_id]
        metric = params.get("metric") or comparison.default_item_metric(experiments)
        if metric not in comparison.metric_keys(experiments):
            raise invalid({"metric": [f"Unknown metric {metric}."]})
        seed = baseline.seed
        if params.get("seed") not in (None, ""):
            seed = runner.clean_seed(params.get("seed"), errors := {})
            if errors:
                raise invalid(errors)
        items = {experiment.pk: list(experiment.items.order_by("position")) for experiment in experiments}
        summaries = [serializers.experiment_payload(experiment, items[experiment.pk]) for experiment in experiments]
        dataset_runs = Experiment.objects.filter(
            workspace=baseline.workspace,
            dataset_snapshot__version_id=(baseline.dataset_snapshot or {}).get("version_id"),
        ).exclude(status=Experiment.Status.DRAFT).count()
        return Response(comparison.compare(experiments, items, baseline=baseline, item_metric=metric, seed=seed,
                                           summaries=summaries, dataset_runs=dataset_runs))
