from django.urls import path
from .views import (
    InsertDataView,
    OpenChatView,
    QueryView,
    InsertTextView,
    InsertURLView,
    JobStatusView,
)

urlpatterns = [
    path("insert-data/", InsertDataView.as_view(), name="insert-data"),
    path("insert-text/", InsertTextView.as_view(), name="insert-text"),
    path("insert-url/", InsertURLView.as_view(), name="insert-url"),
    path("open-chat/", OpenChatView.as_view(), name="open-chat"),
    path("job-status/<str:job_id>/", JobStatusView.as_view(), name="job-status"),
    path("query/", QueryView.as_view(), name="query"),
]