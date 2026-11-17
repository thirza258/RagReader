from django.contrib import admin

from lab.models import DatasetItem, DatasetVersion, EvaluationDataset, Experiment, ExperimentItem


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class DatasetVersionInline(ReadOnlyInline):
    model = DatasetVersion
    fields = ("number", "item_count", "content_hash", "note", "created_at")
    readonly_fields = fields


@admin.register(EvaluationDataset)
class EvaluationDatasetAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "workspace", "updated_at")
    inlines = [DatasetVersionInline]


class DatasetItemInline(ReadOnlyInline):
    model = DatasetItem
    fields = ("position", "item_id", "question")
    readonly_fields = fields


@admin.register(DatasetVersion)
class DatasetVersionAdmin(admin.ModelAdmin):
    # Versions are immutable (save() refuses changes).
    list_display = ("id", "dataset", "number", "item_count", "created_at")
    readonly_fields = ("dataset", "number", "document_ids", "content_hash", "item_count", "note", "created_at")
    inlines = [DatasetItemInline]

    def has_change_permission(self, request, obj=None):
        return False


class ExperimentItemInline(ReadOnlyInline):
    model = ExperimentItem
    fields = ("position", "item_id", "status", "error_code", "latency_ms")
    readonly_fields = fields


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "workspace", "status", "completed_count", "failed_count", "created_at")
    list_filter = ("status", "retrieval_only")
    readonly_fields = ("config", "dataset_snapshot", "index_versions", "environment", "metrics", "warnings",
                       "run_token", "heartbeat_at", "git_commit")
    inlines = [ExperimentItemInline]
