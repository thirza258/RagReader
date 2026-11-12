"""The PRD domain that has no legacy equivalent.

`router.Document`, `router.DocumentVector`, `router.Job` and the legacy
question/answer turn `router.Conversation` stay in the router app: the deep
analysis flow, its migrations and the evaluation app all reference them there.
This app adds what is new around them — workspaces, API tokens, chat threads
(`ChatSession`, called "conversation" in the API), the embedding checkpoint
and, since Phase 2, retrieval runs (one traced RAG request each).
"""
from django.db import IntegrityError, models, transaction
from django.db.models import Q
from django.utils import timezone

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


# ── Retrieval runs (PRD §20, §21, §32) ───────────────────────────────────────

class RetrievalRun(models.Model):
    """One traced RAG request: provenance, latency, tokens, spans, candidates.

    A chat turn records one run, whether it completed or failed. Later
    phases record runs from other sources (evaluation, research) with the
    same shape.
    """

    class Source(models.TextChoices):
        CHAT = "chat"
        EVALUATION = "evaluation"
        RESEARCH = "research"

    class Status(models.TextChoices):
        COMPLETED = "completed"
        FAILED = "failed"

    user = models.ForeignKey("router.GuestUser", on_delete=models.CASCADE, related_name="retrieval_runs")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="retrieval_runs")
    # Deleting a conversation deletes its runs: they hold the question text.
    conversation = models.ForeignKey(
        ChatSession, null=True, blank=True, on_delete=models.CASCADE, related_name="retrieval_runs",
    )
    message = models.ForeignKey(
        ChatMessage, null=True, blank=True, on_delete=models.CASCADE, related_name="retrieval_runs",
    )
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.CHAT, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    # The chat step that failed, as in the SSE error: rewrite, retrieve, generate.
    error_stage = models.CharField(max_length=16, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)

    query_original = models.TextField()
    query_rewritten = models.TextField(blank=True)
    rewrite_applied = models.BooleanField(default=False)
    # first_question, rewritten, unchanged, unusable or failed.
    rewrite_reason = models.CharField(max_length=32, blank=True)

    # Strategy, parameters, models, prompt and index versions (§20).
    provenance = models.JSONField(default=dict, blank=True)

    # Milliseconds; null when the step did not run or did not complete.
    total_ms = models.PositiveIntegerField(null=True, blank=True)
    rewrite_ms = models.PositiveIntegerField(null=True, blank=True)
    retrieval_ms = models.PositiveIntegerField(null=True, blank=True)
    rerank_ms = models.PositiveIntegerField(null=True, blank=True)
    generation_ms = models.PositiveIntegerField(null=True, blank=True)
    first_token_ms = models.PositiveIntegerField(null=True, blank=True)

    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    total_tokens = models.PositiveIntegerField(null=True, blank=True)

    candidate_count = models.PositiveIntegerField(default=0)
    context_count = models.PositiveIntegerField(default=0)
    cited_count = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        indexes = [
            models.Index(fields=["workspace", "-started_at"], name="run_workspace_started"),
            models.Index(fields=["user", "-started_at"], name="run_user_started"),
        ]

    def __str__(self):
        return f"Run {self.pk} ({self.source}, {self.status})"


class RetrievalSpan(models.Model):
    """One node of a run's trace. The tree is stored in pre-order:
    `ordinal` is the position, `parent_ordinal` the parent's (null for the root)."""

    class Status(models.TextChoices):
        COMPLETED = "completed"
        SKIPPED = "skipped"
        FAILED = "failed"

    run = models.ForeignKey(RetrievalRun, on_delete=models.CASCADE, related_name="spans")
    ordinal = models.PositiveIntegerField()
    parent_ordinal = models.PositiveIntegerField(null=True, blank=True)
    depth = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=64)
    label = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COMPLETED)
    # Milliseconds from the start of the run (monotonic clock).
    start_ms = models.FloatField(default=0.0)
    duration_ms = models.FloatField(null=True, blank=True)
    detail = models.CharField(max_length=255, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["run", "ordinal"]
        constraints = [
            models.UniqueConstraint(fields=["run", "ordinal"], name="unique_span_ordinal_per_run"),
        ]

    def __str__(self):
        return f"{self.name} of run {self.run_id}"


class RetrievalCandidate(models.Model):
    """A passage retrieval returned for a run, in rank order."""

    run = models.ForeignKey(RetrievalRun, on_delete=models.CASCADE, related_name="candidates")
    rank = models.PositiveIntegerField()
    document = models.ForeignKey(
        "router.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    # Kept when the document is deleted later.
    document_title = models.CharField(max_length=255, blank=True)
    # Plain ids, not foreign keys: a re-index may replace the chunk rows,
    # and a trace must not stop being storable because of it.
    index_version_id = models.BigIntegerField(null=True, blank=True)
    chunk_id = models.BigIntegerField(null=True, blank=True)
    retrieval_score = models.FloatField(null=True, blank=True)
    rerank_score = models.FloatField(null=True, blank=True)
    selected_for_context = models.BooleanField(default=False)
    cited = models.BooleanField(default=False)
    # The [n] the passage had in the prompt; null when not in the context.
    citation_id = models.PositiveSmallIntegerField(null=True, blank=True)
    page_start = models.PositiveIntegerField(null=True, blank=True)
    page_end = models.PositiveIntegerField(null=True, blank=True)
    char_start = models.PositiveIntegerField(null=True, blank=True)
    char_end = models.PositiveIntegerField(null=True, blank=True)
    snippet = models.TextField(blank=True)

    class Meta:
        ordering = ["run", "rank"]

    def __str__(self):
        return f"Candidate {self.rank} of run {self.run_id}"
