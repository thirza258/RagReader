"""Research tasks (PRD §22–25, §47): evidence-backed work over a workspace's documents.

A task is one request — verify a claim, answer across documents, compare
documents, extract fields, find contradictions, or write a report — run in
the background. It keeps its validated input, the documents and pipeline
version it searched, the evidence it gathered (Evidence objects, PRD §14,
numbered like chat citations) and a kind-specific result whose every
finding points at that evidence. The retrieval and LLM steps are recorded as
one `RetrievalRun` with `source="research"`.
"""
from django.db import models


class ResearchTask(models.Model):
    class Kind(models.TextChoices):
        VERIFY_CLAIM = "verify_claim", "Verify a claim"
        ASK = "ask", "Ask across documents"
        COMPARE = "compare", "Compare documents"
        EXTRACT = "extract", "Extract fields"
        CONTRADICTIONS = "contradictions", "Find contradictions"
        REPORT = "report", "Write a report"

    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        CANCELLED = "cancelled"

    workspace = models.ForeignKey("workspace.Workspace", on_delete=models.CASCADE, related_name="research_tasks")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    title = models.CharField(max_length=200)
    # The validated, kind-specific input (claim, question, dimensions, fields, …).
    input = models.JSONField(default=dict, blank=True)
    # The corpus searched, resolved when the task was created.
    document_ids = models.JSONField(default=list, blank=True)
    # Null after the pipeline is deleted; `pipeline` keeps its snapshot.
    pipeline_version = models.ForeignKey(
        "workspace.PipelineVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="research_tasks",
    )
    pipeline = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True)
    # {"stage": "retrieve" | "analyze" | …, "detail": "…"} while it runs.
    progress = models.JSONField(default=dict, blank=True)
    result = models.JSONField(null=True, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    run = models.ForeignKey(
        "workspace.RetrievalRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="research_tasks",
    )
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    error_stage = models.CharField(max_length=16, blank=True)
    retryable = models.BooleanField(default=False)
    # The claim: a worker owns the task while it is RUNNING with this token.
    run_token = models.UUIDField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["workspace", "-created_at"], name="research_workspace_created")]

    def __str__(self):
        return f"Research task {self.pk}: {self.kind} ({self.status})"
