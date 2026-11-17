from django.urls import path

from research.views import (
    ResearchOptionsView, ResearchTaskCancelView, ResearchTaskDetailView, ResearchTaskExportView, ResearchTaskListView,
    ResearchTaskRetryView,
)

urlpatterns = [
    path("research/options/", ResearchOptionsView.as_view(), name="research-options"),
    path("research/tasks/", ResearchTaskListView.as_view(), name="research-tasks"),
    path("research/tasks/<str:task_id>/", ResearchTaskDetailView.as_view(), name="research-task"),
    path("research/tasks/<str:task_id>/cancel/", ResearchTaskCancelView.as_view(), name="research-task-cancel"),
    path("research/tasks/<str:task_id>/retry/", ResearchTaskRetryView.as_view(), name="research-task-retry"),
    path("research/tasks/<str:task_id>/export/", ResearchTaskExportView.as_view(), name="research-task-export"),
]
