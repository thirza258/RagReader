from datetime import timedelta

from django.db.models import Count, OuterRef, Subquery
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response

from router.models import Document
from workspace.errors import ApiError
from workspace.models import DEFAULT_CONVERSATION_TITLE, ChatMessage, ChatSession
from workspace.serializers import (
    ConversationCreateInput, ConversationPatchInput, MessageInput,
    conversation_payload, message_payload, validated,
)
from workspace.services.chat import INTERRUPTED_MESSAGE, run_chat_turn
from workspace.services.sse import event_stream_response
from workspace.views.base import OwnedAPIView

TAGS = ["Conversations"]
# An answer still "streaming" after this long was cut off by a crash or a
# deploy; its producer is gone and will never finish it.
STALE_STREAM_AFTER = timedelta(minutes=10)
WORKSPACE_PARAM = OpenApiParameter("workspace_id", OpenApiTypes.INT, description="Defaults to the user's default workspace.")
STREAM_PARAM = OpenApiParameter("stream", OpenApiTypes.STR, description="0 returns {user_message, assistant_message} as JSON instead of an event stream.")


def annotated(queryset):
    latest = ChatMessage.objects.filter(session=OuterRef("pk")).order_by("-created_at", "-id").values("content")[:1]
    return queryset.annotate(
        message_count=Count("messages", distinct=True),
        last_message_content=Subquery(latest),
    ).prefetch_related("documents")


def scope_documents(session, override):
    """READY documents a question is asked over, oldest first.

    A message's own document_ids win; otherwise the conversation's selection;
    otherwise every document in the workspace.
    """
    if override:
        ids = [document.pk for document in override]
    else:
        ids = list(session.documents.values_list("pk", flat=True))
    queryset = Document.objects.filter(workspace=session.workspace, user=session.user, status=Document.Status.READY)
    if ids:
        queryset = queryset.filter(pk__in=ids)
    return list(queryset.select_related("current_index").order_by("created_at", "id"))


def expire_stale_streams(session):
    session.messages.filter(
        status=ChatMessage.Status.STREAMING, updated_at__lt=timezone.now() - STALE_STREAM_AFTER,
    ).update(status=ChatMessage.Status.FAILED, error_code="stream_interrupted",
             error_message=INTERRUPTED_MESSAGE, retryable=True, updated_at=timezone.now())


class ConversationListView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="conversations_list", summary="List conversations, most recently active first", parameters=[WORKSPACE_PARAM], responses=OpenApiTypes.OBJECT)
    def get(self, request):
        workspace = self.resolve_workspace(request.query_params.get("workspace_id"))
        sessions = annotated(ChatSession.objects.filter(user=request.user, workspace=workspace)).order_by("-updated_at", "-id")
        return Response({"results": [conversation_payload(session) for session in sessions]})

    @extend_schema(tags=TAGS, operation_id="conversations_create", summary="Start a conversation", request=ConversationCreateInput, responses={201: OpenApiTypes.OBJECT})
    def post(self, request):
        values = validated(ConversationCreateInput, request.data)
        workspace = self.resolve_workspace(values.get("workspace_id"))
        documents = self.documents_in_workspace(workspace, values.get("document_ids"))
        title = (values.get("title") or "").strip()
        session = ChatSession.objects.create(
            user=request.user, workspace=workspace,
            title=title or DEFAULT_CONVERSATION_TITLE, title_is_auto=not title,
        )
        if documents:
            session.documents.set(documents)
        return Response(conversation_payload(session, message_count=0, last_message=""), status=201)


class ConversationDetailView(OwnedAPIView):
    def _payload(self, session):
        return conversation_payload(annotated(ChatSession.objects.filter(pk=session.pk)).get())

    @extend_schema(tags=TAGS, operation_id="conversations_retrieve", summary="Get a conversation", responses=OpenApiTypes.OBJECT)
    def get(self, request, conversation_id):
        return Response(self._payload(self.get_session(conversation_id)))

    @extend_schema(tags=TAGS, operation_id="conversations_partial_update", summary="Rename a conversation or change its documents", request=ConversationPatchInput, responses=OpenApiTypes.OBJECT)
    def patch(self, request, conversation_id):
        session = self.get_session(conversation_id)
        values = validated(ConversationPatchInput, request.data)
        if "document_ids" in values:
            session.documents.set(self.documents_in_workspace(session.workspace, values["document_ids"]))
        if "title" in values:
            title = values["title"].strip()
            if not title:
                raise ApiError("invalid_request", "The request contains invalid or missing fields.",
                               details={"title": ["This field may not be blank."]})
            session.title, session.title_is_auto = title, False
        session.save()
        return Response(self._payload(session))

    @extend_schema(tags=TAGS, operation_id="conversations_destroy", summary="Delete a conversation and its messages", responses={204: None})
    def delete(self, request, conversation_id):
        self.get_session(conversation_id).delete()
        return Response(status=204)


class ConversationMessagesView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="conversations_messages_list", summary="Messages, oldest first", responses=OpenApiTypes.OBJECT)
    def get(self, request, conversation_id):
        session = self.get_session(conversation_id)
        expire_stale_streams(session)
        messages = session.messages.select_related("analysis_turn").order_by("created_at", "id")
        return Response({"results": [message_payload(message) for message in messages]})

    @extend_schema(
        tags=TAGS, operation_id="conversations_messages_create", summary="Ask a question; answers as text/event-stream (see docs/workspace-api.md)",
        parameters=[STREAM_PARAM], request=MessageInput,
        responses={(200, "text/event-stream"): OpenApiTypes.STR, 201: OpenApiTypes.OBJECT},
    )
    def post(self, request, conversation_id):
        session = self.get_session(conversation_id)
        values = validated(MessageInput, request.data)
        question = values["content"].strip()
        override = self.documents_in_workspace(session.workspace, values.get("document_ids"))
        documents = scope_documents(session, override)
        if not documents:
            raise ApiError("no_ready_documents",
                           "No document in this conversation is ready yet. Wait for ingestion to finish, or add a document.",
                           status=409, retryable=True)
        user = request.user

        def producer():
            return run_chat_turn(session, user, question, documents)

        if request.query_params.get("stream") in ("0", "false"):
            user_message = assistant_message = None
            for name, data in producer():
                if name == "message.created":
                    user_message, assistant_message = data["user_message"], data["assistant_message"]
                elif name == "message.completed":
                    assistant_message = data["message"]
                elif name == "error" and data.get("message"):
                    assistant_message = data["message"]
            return Response({"user_message": user_message, "assistant_message": assistant_message}, status=201)
        return event_stream_response(request, producer)
