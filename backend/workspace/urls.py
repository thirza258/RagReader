from django.urls import path

from workspace.views.conversations import ConversationDetailView, ConversationListView, ConversationMessagesView
from workspace.views.documents import (
    DocumentDetailView, DocumentFileView, DocumentIngestionView, DocumentListView, DocumentTextView,
)
from workspace.views.workspaces import WorkspaceDetailView, WorkspaceListView

# Names are prefixed: router.urls already uses "document-detail".
urlpatterns = [
    path("workspaces/", WorkspaceListView.as_view(), name="workspace-list"),
    path("workspaces/<int:workspace_id>/", WorkspaceDetailView.as_view(), name="workspace-detail"),
    path("documents/", DocumentListView.as_view(), name="workspace-document-list"),
    path("documents/<int:document_id>/", DocumentDetailView.as_view(), name="workspace-document-detail"),
    path("documents/<int:document_id>/ingestion/", DocumentIngestionView.as_view(), name="workspace-document-ingestion"),
    path("documents/<int:document_id>/file/", DocumentFileView.as_view(), name="workspace-document-file"),
    path("documents/<int:document_id>/text/", DocumentTextView.as_view(), name="workspace-document-text"),
    path("conversations/", ConversationListView.as_view(), name="workspace-conversation-list"),
    path("conversations/<int:conversation_id>/", ConversationDetailView.as_view(), name="workspace-conversation-detail"),
    path("conversations/<int:conversation_id>/messages/", ConversationMessagesView.as_view(), name="workspace-conversation-messages"),
]
