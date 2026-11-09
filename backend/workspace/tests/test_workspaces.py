"""Workspaces CRUD and the one-default-per-user rule (PRD §7)."""
import os

from django.core.files.storage import default_storage

from workspace.models import Workspace, default_workspace_for
from workspace.tests.helpers import WorkspaceTestCase

KEYS = {"id", "name", "is_default", "document_count", "conversation_count", "created_at", "updated_at"}


class WorkspaceApiTests(WorkspaceTestCase):
    def test_listing_creates_the_default_workspace_once(self):
        first = self.get("/api/v1/workspaces/").json()["results"]
        second = self.get("/api/v1/workspaces/").json()["results"]
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(set(first[0]), KEYS)
        self.assertEqual((first[0]["name"], first[0]["is_default"]), ("My Workspace", True))
        self.assertEqual(Workspace.objects.filter(user=self.user, is_default=True).count(), 1)

    def test_create_rename_and_counts(self):
        default = self.get("/api/v1/workspaces/").json()["results"][0]
        created = self.post("/api/v1/workspaces/", {"name": "  Thesis  "})
        self.assertEqual(created.status_code, 201)
        body = created.json()
        self.assertEqual((body["name"], body["is_default"], body["document_count"]), ("Thesis", False, 0))
        renamed = self.patch(f"/api/v1/workspaces/{body['id']}/", {"name": "Thesis: MultiHop-RAG"})
        self.assertEqual(renamed.json()["name"], "Thesis: MultiHop-RAG")

        self.add_text("Alpha paragraph.", workspace_id=body["id"])
        self.post("/api/v1/conversations/", {"workspace_id": body["id"]})
        fetched = self.get(f"/api/v1/workspaces/{body['id']}/").json()
        self.assertEqual((fetched["document_count"], fetched["conversation_count"]), (1, 1))
        self.assertEqual(self.get(f"/api/v1/workspaces/{default['id']}/").json()["document_count"], 0)

    def test_invalid_names_are_validation_errors(self):
        for payload in ({}, {"name": ""}, {"name": "   "}, {"name": "x" * 121}):
            with self.subTest(payload=payload):
                response = self.post("/api/v1/workspaces/", payload)
                self.assertEqual(response.status_code, 400)
                error = response.json()["error"]
                self.assertEqual(error["code"], "invalid_request")
                self.assertIn("name", error["details"])

    def test_the_last_workspace_cannot_be_deleted(self):
        only = self.get("/api/v1/workspaces/").json()["results"][0]
        response = self.delete(f"/api/v1/workspaces/{only['id']}/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "last_workspace")
        self.assertTrue(Workspace.objects.filter(pk=only["id"]).exists())

    def test_deleting_the_default_promotes_another(self):
        default = self.get("/api/v1/workspaces/").json()["results"][0]
        other = self.post("/api/v1/workspaces/", {"name": "Other"}).json()
        self.assertEqual(self.delete(f"/api/v1/workspaces/{default['id']}/").status_code, 204)
        remaining = self.get("/api/v1/workspaces/").json()["results"]
        self.assertEqual([(w["id"], w["is_default"]) for w in remaining], [(other["id"], True)])

    def test_deleting_a_workspace_removes_its_documents_and_files(self):
        self.get("/api/v1/workspaces/")
        doomed = self.post("/api/v1/workspaces/", {"name": "Doomed"}).json()
        document = self.ready_text_document("Alpha paragraph about embeddings.")
        # ready_text_document uses the default workspace; add one to Doomed too.
        moved = self.add_text("Beta paragraph about search.", workspace_id=doomed["id"])
        self.assertTrue(self.ingest_last_queued())
        from router.models import Document
        stored = Document.objects.get(pk=moved["id"])
        paths = [stored.source_path, stored.extracted_text_path]
        index = stored.current_index.vectorstore_location
        self.assertTrue(all(default_storage.exists(path) for path in paths))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.delete(f"/api/v1/workspaces/{doomed['id']}/").status_code, 204)
        self.assertFalse(Document.objects.filter(pk=moved["id"]).exists())
        self.assertFalse(any(default_storage.exists(path) for path in paths))
        self.assertFalse(os.path.exists(index))
        self.assertTrue(Document.objects.filter(pk=document["id"]).exists())

    def test_default_workspace_for_promotes_instead_of_duplicating(self):
        kept = Workspace.objects.create(user=self.user, name="Kept", is_default=False)
        self.assertEqual(default_workspace_for(self.user).pk, kept.pk)
        self.assertEqual(Workspace.objects.filter(user=self.user).count(), 1)
