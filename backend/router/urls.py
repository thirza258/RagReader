from django.urls import path
from .views import (
    InsertDataView,
    OpenChatView,
    QueryView,
)

urlpatterns = [
    path("insert-data/", InsertDataView.as_view(), name="insert-data"),
    path("open-chat/", OpenChatView.as_view(), name="open-chat"),
    path("query/", QueryView.as_view(), name="query"),
]