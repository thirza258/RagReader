from django.contrib import admin

from workspace.models import ApiToken, ChatMessage, ChatSession, Workspace


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
