"""The backfill that gives legacy documents a workspace and a status."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from router.models import Document
from workspace.models import Workspace

BEFORE = [("router", "0014_analysisbatch_execution_token_and_more"), ("workspace", None)]


class BackfillMigrationTests(TransactionTestCase):
    def test_legacy_documents_get_a_default_workspace_and_an_honest_status(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate(BEFORE)
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        old = executor.loader.project_state([BEFORE[0]]).apps
        User, OldDocument, VectorStore, Vector = (
            old.get_model("router", name) for name in ("GuestUser", "Document", "VectorStore", "DocumentVector")
        )
        owner = User.objects.create(username="legacy", email="legacy@example.com")
        idle = User.objects.create(username="idle", email="idle@example.com")
        indexed = OldDocument.objects.create(user=owner, name="indexed.pdf", source_type="pdf")
        unindexed = OldDocument.objects.create(user=owner, name="notes", source_type="text")
        sparse_only = OldDocument.objects.create(user=owner, name="sparse.txt", source_type="txt")
        store = VectorStore.objects.create(base_path="./vector_stores")
        Vector.objects.create(document=indexed, vectorstore=store, vectorstore_location="old.pkl", document_location="x", status="ready", method="dense")
        newest = Vector.objects.create(document=indexed, vectorstore=store, vectorstore_location="new.pkl", document_location="x", status="ready", method="dense")
        Vector.objects.create(document=sparse_only, vectorstore=store, vectorstore_location="s.pkl", document_location="x", status="ready", method="sparse")

        MigrationExecutor(connection).migrate(latest)

        workspace = Workspace.objects.get(user_id=owner.pk)
        self.assertEqual((workspace.name, workspace.is_default), ("My Workspace", True))
        self.assertFalse(Workspace.objects.filter(user_id=idle.pk).exists())
        ready = Document.objects.get(pk=indexed.pk)
        self.assertEqual((ready.workspace_id, ready.status, ready.progress, ready.current_index_id), (workspace.pk, "READY", 100, newest.pk))
        self.assertIsNotNone(ready.ingested_at)
        for pk in (unindexed.pk, sparse_only.pk):
            failed = Document.objects.get(pk=pk)
            self.assertEqual((failed.workspace_id, failed.status, failed.error_code, failed.retryable), (workspace.pk, "FAILED", "not_indexed", True))
            self.assertEqual(failed.error_message, "This document was added before background ingestion. Re-index it to use it in chat.")
