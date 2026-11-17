"""Owner-scoped lookups for the evaluation lab's views."""
from lab.models import EvaluationDataset, Experiment
from workspace.errors import ApiError
from workspace.views.base import OwnedAPIView, parse_id


class LabView(OwnedAPIView):
    """Token required; another user's dataset or experiment is a 404, like a missing one."""

    def get_dataset(self, dataset_id):
        pk = parse_id(dataset_id)
        dataset = (EvaluationDataset.objects.select_related("workspace", "workspace__user")
                   .filter(pk=pk, workspace__user=self.request.user).first() if pk else None)
        if dataset is None:
            raise ApiError("not_found", "Dataset not found.", status=404)
        return dataset

    def get_experiment(self, experiment_id):
        pk = parse_id(experiment_id)
        experiment = (Experiment.objects.select_related("workspace", "workspace__user", "pipeline_version__pipeline")
                      .filter(pk=pk, workspace__user=self.request.user).first() if pk else None)
        if experiment is None:
            raise ApiError("not_found", "Experiment not found.", status=404)
        return experiment


def invalid(details):
    return ApiError("invalid_request", "The request contains invalid or missing fields.", details=details)
