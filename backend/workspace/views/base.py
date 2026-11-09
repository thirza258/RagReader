"""Authentication, ownership and errors shared by every workspace API view."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from router.models import Document
from workspace.auth import GuestTokenAuthentication
from workspace.errors import ApiError, api_exception_handler
from workspace.models import ChatSession, Workspace, default_workspace_for

# Ids above this cannot exist and make some database drivers raise instead of
# simply finding nothing.
MAX_ID = 2 ** 63 - 1


def parse_id(value):
    """An int id from a path, query or body value, or None when malformed."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        return None
    return number if 0 < number <= MAX_ID else None


def not_found(label):
    return ApiError("not_found", f"{label} not found.", status=404)


class OwnedAPIView(APIView):
    """Base view: token required, objects loaded only through owner-filtered helpers.

    An object that belongs to someone else is indistinguishable from one that
    does not exist: both are 404, so ids cannot be probed.
    """

    authentication_classes = [GuestTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get_exception_handler(self):
        return api_exception_handler

    def get_workspace(self, workspace_id):
        pk = parse_id(workspace_id)
        workspace = Workspace.objects.filter(pk=pk, user=self.request.user).first() if pk else None
        if workspace is None:
            raise not_found("Workspace")
        return workspace

    def resolve_workspace(self, workspace_id):
        """The named workspace, or the user's default when none is given."""
        if workspace_id in (None, ""):
            return default_workspace_for(self.request.user)
        return self.get_workspace(workspace_id)

    def get_document(self, document_id):
        pk = parse_id(document_id)
        document = (
            Document.objects.select_related("current_index", "user").filter(pk=pk, user=self.request.user).first()
            if pk else None
        )
        if document is None:
            raise not_found("Document")
        return document

    def get_session(self, session_id):
        pk = parse_id(session_id)
        session = (
            ChatSession.objects.select_related("workspace").filter(pk=pk, user=self.request.user).first()
            if pk else None
        )
        if session is None:
            raise not_found("Conversation")
        return session

    def documents_in_workspace(self, workspace, document_ids, field="document_ids"):
        """Validate client-sent document ids against one of the user's workspaces.

        The message is the same whether an id belongs to another workspace,
        another user or nobody, so this cannot be used to probe ids either.
        """
        if not document_ids:
            return []
        wanted = list(dict.fromkeys(document_ids))
        found = {
            document.pk: document
            for document in Document.objects.filter(pk__in=wanted, workspace=workspace, user=self.request.user)
        }
        missing = [pk for pk in wanted if pk not in found]
        if missing:
            raise ApiError(
                "invalid_request", "The request contains invalid or missing fields.",
                details={field: [f"Document {pk} is not in this workspace." for pk in missing]},
            )
        return [found[pk] for pk in wanted]
