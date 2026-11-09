"""The PRD domain that has no legacy equivalent.

`router.Document`, `router.DocumentVector`, `router.Job` and the legacy
question/answer turn `router.Conversation` stay in the router app: the deep
analysis flow, its migrations and the evaluation app all reference them there.
This app adds what is new around them — workspaces, API tokens, chat threads
(`ChatSession`, called "conversation" in the API) and the embedding checkpoint.
"""
from django.db import IntegrityError, models, transaction
from django.db.models import Q

DEFAULT_WORKSPACE_NAME = "My Workspace"
DEFAULT_CONVERSATION_TITLE = "New conversation"


class Workspace(models.Model):
    user = models.ForeignKey("router.GuestUser", on_delete=models.CASCADE, related_name="workspaces")
    name = models.CharField(max_length=120)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "created_at", "id"]
        constraints = [
            # "Every user has exactly one default workspace": the database
            # enforces the "at most one" half, so concurrent first requests
            # cannot both create one.
            models.UniqueConstraint(
                fields=["user"], condition=Q(is_default=True),
                name="one_default_workspace_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.user_id})"


def default_workspace_for(user):
    """The user's default workspace, created (or promoted) on first need."""
    workspace = Workspace.objects.filter(user=user, is_default=True).first()
    if workspace is not None:
        return workspace
    oldest = Workspace.objects.filter(user=user).order_by("created_at", "id").first()
    try:
        # A savepoint keeps a lost race from poisoning the caller's transaction.
        with transaction.atomic():
            if oldest is not None:
                Workspace.objects.filter(pk=oldest.pk).update(is_default=True)
            else:
                Workspace.objects.create(user=user, name=DEFAULT_WORKSPACE_NAME, is_default=True)
    except IntegrityError:
        pass  # A concurrent request made one first; the constraint keeps it unique.
    return Workspace.objects.get(user=user, is_default=True)


class ApiToken(models.Model):
    """A bearer token. Only its SHA-256 is stored; the plaintext is shown once."""

    user = models.ForeignKey("router.GuestUser", on_delete=models.CASCADE, related_name="api_tokens")
    key_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"ApiToken {self.pk} ({self.user_id})"


class ChatSession(models.Model):
    """A persistent conversation thread (the API calls it a conversation).

    Not to be confused with `router.Conversation`, which is one legacy
    question/answer turn and the anchor for ground truth and deep analysis.
    """

    user = models.ForeignKey("router.GuestUser", on_delete=models.CASCADE, related_name="chat_sessions")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="conversations")
    title = models.CharField(max_length=200, default=DEFAULT_CONVERSATION_TITLE)
    # True until the user renames the thread; the first question sets the title.
    title_is_auto = models.BooleanField(default=True)
    # Empty means "every READY document in the workspace at question time".
    documents = models.ManyToManyField("router.Document", blank=True, related_name="chat_sessions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return self.title


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"

    class Status(models.TextChoices):
        STREAMING = "streaming"
        COMPLETE = "complete"
        FAILED = "failed"

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COMPLETE)
    citations = models.JSONField(default=list, blank=True)
    retrieval = models.JSONField(null=True, blank=True)
    token_usage = models.JSONField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    retryable = models.BooleanField(default=False)
    # Links a single-document answer to the legacy turn the deep-analysis
    # flow (/ground-truth/{conversation_id}/{document_id}) is keyed by.
    analysis_turn = models.ForeignKey(
        "router.Conversation", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="chat_messages",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.role} message {self.pk}"


class EmbeddingCacheEntry(models.Model):
    """One committed chunk embedding: the ingestion checkpoint (PRD §41).

    Every embedded batch is committed on its own, so a retry after a failure
    at chunk 700 of 1,000 only embeds what is missing, and `_build_index`
    reuses these vectors instead of calling the provider again.
    """

    document = models.ForeignKey("router.Document", on_delete=models.CASCADE, related_name="embedding_cache")
    model = models.CharField(max_length=200)
    text_hash = models.CharField(max_length=64)
    dimensions = models.PositiveIntegerField()
    vector = models.BinaryField()  # float32, little-endian
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "model", "text_hash"],
                name="unique_embedding_per_document_model_text",
            ),
        ]

    def __str__(self):
        return f"Embedding {self.text_hash[:12]} of document {self.document_id}"
