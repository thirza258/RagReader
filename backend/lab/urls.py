from django.urls import path

from lab.views.datasets import (
    DatasetDetailView, DatasetDraftView, DatasetExportView, DatasetImportNewView, DatasetImportView,
    DatasetItemDetailView, DatasetItemsView, DatasetListView, DatasetVersionsView,
)
from lab.views.experiments import (
    ExperimentCancelView, ExperimentCompareView, ExperimentDetailView, ExperimentItemsView, ExperimentListView,
    ExperimentRerunView, ExperimentStartView,
)

urlpatterns = [
    path("evaluations/datasets/", DatasetListView.as_view(), name="lab-datasets"),
    path("evaluations/datasets/import/", DatasetImportNewView.as_view(), name="lab-dataset-import-new"),
    path("evaluations/datasets/<str:dataset_id>/", DatasetDetailView.as_view(), name="lab-dataset"),
    path("evaluations/datasets/<str:dataset_id>/versions/", DatasetVersionsView.as_view(), name="lab-dataset-versions"),
    # Before items/<item_id>/: "from-message" is also a valid item id.
    path("evaluations/datasets/<str:dataset_id>/items/from-message/", DatasetDraftView.as_view(), name="lab-dataset-draft"),
    path("evaluations/datasets/<str:dataset_id>/items/", DatasetItemsView.as_view(), name="lab-dataset-items"),
    path("evaluations/datasets/<str:dataset_id>/items/<str:item_id>/", DatasetItemDetailView.as_view(),
         name="lab-dataset-item"),
    path("evaluations/datasets/<str:dataset_id>/import/", DatasetImportView.as_view(), name="lab-dataset-import"),
    path("evaluations/datasets/<str:dataset_id>/export/", DatasetExportView.as_view(), name="lab-dataset-export"),
    path("experiments/", ExperimentListView.as_view(), name="lab-experiments"),
    path("experiments/compare/", ExperimentCompareView.as_view(), name="lab-experiments-compare"),
    path("experiments/<str:experiment_id>/", ExperimentDetailView.as_view(), name="lab-experiment"),
    path("experiments/<str:experiment_id>/start/", ExperimentStartView.as_view(), name="lab-experiment-start"),
    path("experiments/<str:experiment_id>/cancel/", ExperimentCancelView.as_view(), name="lab-experiment-cancel"),
    path("experiments/<str:experiment_id>/rerun/", ExperimentRerunView.as_view(), name="lab-experiment-rerun"),
    path("experiments/<str:experiment_id>/items/", ExperimentItemsView.as_view(), name="lab-experiment-items"),
]
