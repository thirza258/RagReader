from django.contrib import admin

from research.models import ResearchTask


@admin.register(ResearchTask)
class ResearchTaskAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "kind", "workspace", "status", "created_at")
    list_filter = ("kind", "status")
    readonly_fields = ("input", "document_ids", "pipeline", "result", "evidence", "progress", "run_token",
                       "heartbeat_at")
