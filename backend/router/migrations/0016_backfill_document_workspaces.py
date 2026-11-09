"""Give every legacy document a workspace and an honest ingestion status.

Documents uploaded before background ingestion have no status of their own:
the old flow kept it on the user's latest Job. A document that already has a
ready dense index can be chatted with as-is, so it becomes READY and points at
the newest such index. Everything else cannot be used by the workspace chat
until it is indexed, which the user does with one "Re-index" click.
"""
from django.db import migrations

DEFAULT_WORKSPACE_NAME = "My Workspace"
NOT_INDEXED_MESSAGE = "This document was added before background ingestion. Re-index it to use it in chat."


def backfill(apps, schema_editor):
    alias = schema_editor.connection.alias
    Document = apps.get_model("router", "Document")
    DocumentVector = apps.get_model("router", "DocumentVector")
    Workspace = apps.get_model("workspace", "Workspace")
    documents = Document.objects.using(alias)

    user_ids = documents.filter(workspace__isnull=True).values_list("user_id", flat=True).distinct()
    for user_id in list(user_ids):
        workspace = Workspace.objects.using(alias).filter(user_id=user_id, is_default=True).first()
        if workspace is None:
            workspace = Workspace.objects.using(alias).create(
                user_id=user_id, name=DEFAULT_WORKSPACE_NAME, is_default=True,
            )
        documents.filter(user_id=user_id, workspace__isnull=True).update(workspace=workspace)

    for document in documents.all().iterator():
        vector = (
            DocumentVector.objects.using(alias)
            .filter(document_id=document.pk, status="ready", method="dense")
            .order_by("-created_at", "-id")
            .first()
        )
        if vector is not None:
            documents.filter(pk=document.pk).update(
                status="READY", progress=100, status_detail="Ready", current_index=vector,
                ingested_at=vector.created_at, error_stage="", error_code="", error_message="",
                retryable=False,
            )
        else:
            documents.filter(pk=document.pk).update(
                status="FAILED", progress=0, status_detail="Not indexed", current_index=None,
                error_stage="", error_code="not_indexed", error_message=NOT_INDEXED_MESSAGE,
                retryable=True,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("router", "0015_document_workspace_ingestion_fields"),
        ("workspace", "0001_initial"),
    ]

    operations = [
        # Reversing only drops the columns (0015), so there is nothing to undo here.
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
