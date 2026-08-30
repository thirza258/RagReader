from django.urls import path
from .views import (
    AnalysisConfigView,
    InsertDataView,
    OpenChatView,
    QueryView,
    InsertTextView,
    InsertURLView,
    JobStatusView,
    StartAnalysisView,
    AnalysisStatusView,
    ConversationHistoryView,
    ConversationView,
    DocumentView
)
from django.urls import re_path
from .consumers import AnalysisConsumer

urlpatterns = [
    path("insert-data/", InsertDataView.as_view(), name="insert-data"),
    path("insert-text/", InsertTextView.as_view(), name="insert-text"),
    path("insert-url/", InsertURLView.as_view(), name="insert-url"),
    path("open-chat/", OpenChatView.as_view(), name="open-chat"),
    path("job-status/<str:job_id>/", JobStatusView.as_view(), name="job-status"),
    path("query/", QueryView.as_view(), name="query"),
    path("analysis-config/", AnalysisConfigView.as_view(), name="analysis-config"),
    path("start-analysis/", StartAnalysisView.as_view(), name="start-analysis"),
    path("analysis-status/<str:job_id>/", AnalysisStatusView.as_view(), name="analysis-status"),
    path("document/<str:username>/", DocumentView.as_view(), name="document-detail"),
    path("conversation-history/<str:username>/", ConversationHistoryView.as_view(), name="conversation-history"),
    path("conversation/<str:conversation_id>/", ConversationView.as_view(), name="conversation")
    
]

websocket_urlpatterns = [
    re_path(r"^/?ws/analysis/(?P<job_id>[\w-]+)/?$", AnalysisConsumer.as_asgi()),
]