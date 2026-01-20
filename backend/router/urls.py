from django.urls import path
from .views import (
    InsertDataView,
    OpenChatView,
    QueryView,
    InsertTextView,
    InsertURLView,
)

urlpatterns = [
    path("insert-data/", InsertDataView.as_view(), name="insert-data"),
    path("insert-text/", InsertTextView.as_view(), name="insert-text"),
    path("insert-url/", InsertURLView.as_view(), name="insert-url"),
    path("open-chat/", OpenChatView.as_view(), name="open-chat"),
    path("query/", QueryView.as_view(), name="query"),
    
    
]