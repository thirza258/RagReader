"""The evaluation lab (PRD §26–31, §42): datasets, versions and experiments.

Named apart from the legacy `evaluation` app (ground truth, chunk metrics,
Ragas for deep analysis), which keeps its own models and endpoints.

- An `EvaluationDataset` belongs to a workspace. Its content lives in
  immutable `DatasetVersion` rows, each with its own `DatasetItem` copies:
  every edit that changes the content hash adds version n + 1, so an
  experiment that names "v3" names exact questions and expected sources.
- An `Experiment` runs one dataset version through one pipeline version in
  the background and keeps everything needed to reproduce it: the pipeline
  configuration, the documents and index versions searched, the seed, the
  environment and the git commit. `ExperimentItem` rows hold a snapshot of
  each dataset item and its results, linked to the item's retrieval run.
"""
from django.db import models


class ImmutableRecordError(Exception):
    """A saved dataset version or item was about to be changed."""


class EvaluationDataset(models.Model):
    workspace = models.ForeignKey("workspace.Workspace", on_delete=models.CASCADE, related_name="evaluation_datasets")
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return f"{self.name} (workspace {self.workspace_id})"


class DatasetVersion(models.Model):
    """One immutable snapshot of a dataset (PRD §42)."""

    dataset = models.ForeignKey(EvaluationDataset, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    # The corpus searched. Empty means every READY document of the workspace
    # when an experiment starts (the experiment records which those were).
    document_ids = models.JSONField(default=list, blank=True)
    # sha256 of the canonical JSON of the document ids and the items.
    content_hash = models.CharField(max_length=64)
    item_count = models.PositiveIntegerField(default=0)
    # What changed, for people: "Added 1 item", "Imported 20 items", …
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["dataset", "-number"]
        constraints = [
            models.UniqueConstraint(fields=["dataset", "number"], name="unique_dataset_version_number"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Dataset versions cannot be changed; edit the dataset to add a version.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Dataset {self.dataset_id} v{self.number}"


class DatasetItem(models.Model):
    """One question of one dataset version; never updated after it is saved."""

    version = models.ForeignKey(DatasetVersion, on_delete=models.CASCADE, related_name="items")
    position = models.PositiveIntegerField()
    # The item's stable key across versions ("q1", "Q-042", …).
    item_id = models.CharField(max_length=64)
    question = models.TextField()
    expected_answer = models.TextField(blank=True)
    expected_sources = models.JSONField(default=list, blank=True)
    # The conversation before the question, oldest first (follow-up questions).
    history = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["version", "position"]
        constraints = [
            models.UniqueConstraint(fields=["version", "position"], name="unique_dataset_item_position"),
            models.UniqueConstraint(fields=["version", "item_id"], name="unique_dataset_item_id"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Dataset items cannot be changed; edit the dataset to add a version.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item_id} of dataset version {self.version_id}"


class Experiment(models.Model):
    """One dataset version run through one pipeline version (PRD §29)."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        QUEUED = "queued"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        CANCELLED = "cancelled"

    workspace = models.ForeignKey("workspace.Workspace", on_delete=models.CASCADE, related_name="experiments")
    name = models.CharField(max_length=200)
    hypothesis = models.TextField(blank=True)
    conclusion = models.TextField(blank=True)
    # Null after the dataset is deleted; `dataset_snapshot` and the items'
    # snapshots keep what was evaluated.
    dataset_version = models.ForeignKey(
        DatasetVersion, null=True, blank=True, on_delete=models.SET_NULL, related_name="experiments",
    )
    dataset_snapshot = models.JSONField(default=dict, blank=True)
    # Null after the pipeline is deleted; `config["pipeline"]` keeps the configuration.
    pipeline_version = models.ForeignKey(
        "workspace.PipelineVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="experiments",
    )
    # Everything needed to rerun (docs/prd-implementation.md, Phase 4).
    config = models.JSONField(default=dict, blank=True)
    index_versions = models.JSONField(default=list, blank=True)
    retrieval_only = models.BooleanField(default=False)
    seed = models.BigIntegerField(default=42)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    retryable = models.BooleanField(default=False)
    # The claim: a worker owns the run while the status is RUNNING with its token.
    run_token = models.UUIDField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)

    item_count = models.PositiveIntegerField(default=0)
    completed_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    # Aggregates, stored when the run ends (recomputed on read until then).
    metrics = models.JSONField(null=True, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    git_commit = models.CharField(max_length=64, null=True, blank=True)
    environment = models.JSONField(default=dict, blank=True)
    rerun_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reruns")
    # Summed active time of every worker run, in milliseconds.
    runtime_ms = models.PositiveBigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["workspace", "-created_at"], name="experiment_workspace_created")]

    def __str__(self):
        return f"Experiment {self.pk}: {self.name} ({self.status})"


class ExperimentItem(models.Model):
    """One dataset item of an experiment: its snapshot, run and results."""

    class Status(models.TextChoices):
        PENDING = "pending"
        COMPLETED = "completed"
        FAILED = "failed"

    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name="items")
    position = models.PositiveIntegerField()
    item_id = models.CharField(max_length=64)
    question = models.TextField()
    expected_answer = models.TextField(blank=True)
    expected_sources = models.JSONField(default=list, blank=True)
    history = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    # rewrite, retrieve, generate or judge.
    error_stage = models.CharField(max_length=16, blank=True)
    run = models.ForeignKey(
        "workspace.RetrievalRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="evaluation_items",
    )
    answer = models.TextField(blank=True)
    # query, matching, retrieved, alternative (docs/prd-implementation.md).
    details = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    metric_reasons = models.JSONField(default=dict, blank=True)
    failure_labels = models.JSONField(default=list, blank=True)

    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    retrieval_ms = models.PositiveIntegerField(null=True, blank=True)
    generation_ms = models.PositiveIntegerField(null=True, blank=True)
    judge_ms = models.PositiveIntegerField(null=True, blank=True)
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    total_tokens = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["experiment", "position"]
        constraints = [
            models.UniqueConstraint(fields=["experiment", "position"], name="unique_experiment_item_position"),
        ]

    def __str__(self):
        return f"{self.item_id} of experiment {self.experiment_id}"
