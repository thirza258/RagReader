from django.contrib import admin

from workspace.models import (
    ApiToken, ChatMessage, ChatSession, RetrievalCandidate, RetrievalRun, RetrievalSpan, Workspace,
)


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "user", "is_default", "created_at")
    list_filter = ("is_default",)


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    # The hash is useless to a reader and the plaintext is never stored.
    list_display = ("id", "user", "created_at", "last_used_at")
    exclude = ("key_hash",)


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "user", "workspace", "updated_at")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "role", "status", "created_at")
    list_filter = ("role", "status")


class _ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class RetrievalSpanInline(_ReadOnlyInline):
    model = RetrievalSpan
    fields = ("ordinal", "parent_ordinal", "depth", "name", "status", "start_ms", "duration_ms", "detail", "error_code")
    readonly_fields = fields


class RetrievalCandidateInline(_ReadOnlyInline):
    model = RetrievalCandidate
    fields = ("rank", "document_title", "chunk_id", "page_start", "retrieval_score", "rerank_score", "selected_for_context", "cited", "citation_id")
    readonly_fields = fields


@admin.register(RetrievalRun)
class RetrievalRunAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "workspace", "source", "status", "error_stage", "error_code", "total_ms", "first_token_ms", "total_tokens", "started_at")
    list_filter = ("source", "status", "error_stage")
    search_fields = ("query_original", "error_code")
    raw_id_fields = ("user", "workspace", "conversation", "message")
    date_hierarchy = "started_at"
    inlines = [RetrievalSpanInline, RetrievalCandidateInline]


@admin.register(RetrievalSpan)
class RetrievalSpanAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "ordinal", "name", "status", "start_ms", "duration_ms", "error_code")
    list_filter = ("status", "name")
    raw_id_fields = ("run",)


@admin.register(RetrievalCandidate)
class RetrievalCandidateAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "rank", "document_title", "retrieval_score", "selected_for_context", "cited")
    list_filter = ("selected_for_context", "cited")
    raw_id_fields = ("run", "document")
