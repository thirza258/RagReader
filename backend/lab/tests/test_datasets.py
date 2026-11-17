"""Datasets: validation, immutable versions, import/export, drafts from chat (PRD §26, §42)."""
import json
import os

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

from django.core.files.uploadedfile import SimpleUploadedFile

from lab.models import DatasetItem, DatasetVersion, ImmutableRecordError
from lab.tests.helpers import LabTestCase
from workspace.models import ChatMessage
from workspace.tests.helpers import bearer, make_user, parse_sse


class DatasetVersionTests(LabTestCase):
    def setUp(self):
        super().setUp()
        self.document, self.chunks = self.ready_letters()

    def test_create_validates_and_starts_at_version_one(self):
        dataset = self.create_dataset([
            {"question": "Which letter is alpha?", "tags": ["greek", "greek"],
             "expected_sources": [{"document_id": self.document["id"], "page": 1}]},
        ])
        self.assertEqual(dataset["version"]["number"], 1)
        items = self.get(f"/api/v1/evaluations/datasets/{dataset['id']}/items/").json()["results"]
        self.assertEqual(items[0]["item_id"], "q1")
        self.assertEqual(items[0]["tags"], ["greek"])
        self.assertEqual(items[0]["expected_sources"][0]["page_end"], 1)
        self.assertEqual(items[0]["expected_sources"][0]["document_title"], "Greek letters")

        bad = self.post("/api/v1/evaluations/datasets/", {"name": "Bad", "items": [
            {"question": ""}, {"question": "ok", "expected_sources": [{"document_id": 999999}]},
            {"question": "range", "expected_sources": [{"document_id": self.document["id"], "char_start": 5}]},
        ]})
        self.assertEqual(bad.status_code, 400)
        details = bad.json()["error"]["details"]
        self.assertTrue(any(key.startswith("items[0]") for key in details))
        self.assertTrue(any(key.startswith("items[1]") for key in details))
        self.assertTrue(any(key.startswith("items[2]") for key in details))

    def test_edits_create_versions_and_identical_content_does_not(self):
        dataset = self.create_dataset([{"item_id": "a", "question": "Alpha?"}])
        path = f"/api/v1/evaluations/datasets/{dataset['id']}"
        added = self.post(f"{path}/items/", {"question": "Gamma?", "base_version": 1})
        self.assertEqual(added.status_code, 201, added.content)
        self.assertEqual(added.json()["version"]["number"], 2)
        same = self.patch(f"{path}/", {"items": [{"item_id": "a", "question": "Alpha?"}, {"item_id": "q2", "question": "Gamma?"}]})
        self.assertFalse(same.json()["version_created"])
        renamed = self.patch(f"{path}/", {"name": "Renamed"})
        self.assertEqual((renamed.json()["name"], renamed.json()["version_count"]), ("Renamed", 2))
        edited = self.patch(f"{path}/items/a/", {"question": "Alpha, really?"})
        self.assertEqual(edited.json()["version"]["number"], 3)
        conflict = self.post(f"{path}/items/", {"question": "Delta?", "base_version": 2})
        self.assertEqual((conflict.status_code, conflict.json()["error"]["code"]), (409, "version_conflict"))
        deleted = self.delete(f"{path}/items/a/")
        self.assertEqual(deleted.json()["version"]["item_count"], 1)
        old = self.get(f"{path}/items/?version=1").json()
        self.assertEqual([item["question"] for item in old["results"]], ["Alpha?"])
        versions = self.get(f"{path}/versions/").json()["results"]
        self.assertEqual([version["number"] for version in versions], [4, 3, 2, 1])
        self.assertEqual(len({version["content_hash"] for version in versions}), 4)

    def test_saved_versions_and_items_cannot_change(self):
        dataset = self.create_dataset([{"question": "Alpha?"}])
        version = DatasetVersion.objects.get(dataset_id=dataset["id"])
        version.note = "rewritten history"
        with self.assertRaises(ImmutableRecordError):
            version.save()
        item = DatasetItem.objects.get(version=version)
        item.question = "changed"
        with self.assertRaises(ImmutableRecordError):
            item.save()

    def test_checks_flag_missing_sources_and_duplicates(self):
        dataset = self.create_dataset([{"item_id": "a", "question": "What is alpha?"},
                                       {"item_id": "b", "question": "what is ALPHA"}])
        checks = dataset["version"]["checks"]
        self.assertEqual(checks["items_without_sources"], ["a", "b"])
        self.assertEqual(checks["duplicate_questions"], [["a", "b"]])

    def test_csv_import_with_compact_sources_and_round_trip_export(self):
        alpha = self.chunks["alpha"]
        csv_text = ("item_id,question,expected_sources,tags,notes\n"
                    f"x1,Which letter is alpha?,{self.document['id']}#c{alpha.pk},greek; letters,ignored\n"
                    f"x2,\"Pages, too?\",{self.document['id']}#p1-2,,\n")
        response = self.client.post(
            "/api/v1/evaluations/datasets/import/",
            {"file": SimpleUploadedFile("letters.csv", csv_text.encode()), "name": "From CSV"}, **self.auth,
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["imported"], body["ignored_columns"]), (2, ["notes"]))
        dataset_id = body["dataset"]["id"]
        items = self.get(f"/api/v1/evaluations/datasets/{dataset_id}/items/").json()["results"]
        self.assertEqual(items[0]["expected_sources"][0]["chunk_id"], alpha.pk)
        self.assertEqual((items[1]["expected_sources"][0]["page"], items[1]["expected_sources"][0]["page_end"]), (1, 2))
        self.assertEqual(items[0]["tags"], ["greek", "letters"])

        exported = self.get(f"/api/v1/evaluations/datasets/{dataset_id}/export/?format=json")
        self.assertEqual(exported["Content-Disposition"], f'attachment; filename="dataset-{dataset_id}-v1.json"')
        payload = json.loads(exported.content)
        self.assertEqual(payload["format"], "ragreader-dataset")
        reimported = self.post("/api/v1/evaluations/datasets/import/", {"format": "json", "content": exported.content.decode()})
        self.assertEqual(reimported.status_code, 201, reimported.content)
        copy = reimported.json()["dataset"]
        self.assertEqual(copy["name"], "From CSV")
        self.assertEqual(copy["version"]["content_hash"], body["dataset"]["version"]["content_hash"])
        csv_export = self.get(f"/api/v1/evaluations/datasets/{dataset_id}/export/?format=csv")
        self.assertTrue(csv_export.content.decode().startswith("item_id,question,expected_answer,expected_sources"))

    def test_import_into_an_existing_dataset_appends_or_replaces(self):
        dataset = self.create_dataset([{"question": "Alpha?"}])
        path = f"/api/v1/evaluations/datasets/{dataset['id']}/import/"
        appended = self.post(path, {"items": [{"question": "Gamma?"}]})
        self.assertEqual((appended.status_code, appended.json()["version"]["item_count"]), (201, 2))
        replaced = self.post(path, {"items": [{"question": "Delta?"}], "mode": "replace"})
        self.assertEqual(replaced.json()["version"]["item_count"], 1)

    def test_draft_from_a_chat_answer_suggests_cited_sources_without_the_answer(self):
        conversation = self.post("/api/v1/conversations/", {}).json()
        self.chat.answer = "Alpha comes first [1]."
        response = self.post(f"/api/v1/conversations/{conversation['id']}/messages/", {"content": "Which letter is alpha?"})
        parse_sse(b"".join(response.streaming_content))
        message = ChatMessage.objects.get(role="assistant")
        dataset = self.create_dataset([])
        draft = self.get(f"/api/v1/evaluations/datasets/{dataset['id']}/items/from-message/?message_id={message.pk}").json()
        self.assertEqual(draft["draft"]["question"], "Which letter is alpha?")
        self.assertEqual(draft["draft"]["expected_answer"], "")
        self.assertEqual(len(draft["draft"]["expected_sources"]), 1)
        self.assertEqual(draft["draft"]["expected_sources"][0]["chunk_id"], message.citations[0]["chunk_id"])
        self.assertTrue(draft["sources"][0]["suggested"])
        other = bearer(make_user("mallory"))
        self.assertEqual(self.get(f"/api/v1/evaluations/datasets/{dataset['id']}/items/from-message/?message_id={message.pk}",
                                  auth=other).status_code, 404)
        unknown = self.get(f"/api/v1/evaluations/datasets/{dataset['id']}/items/from-message/?message_id=999999")
        self.assertEqual(unknown.status_code, 400)

    def test_datasets_list_per_workspace_and_delete(self):
        dataset = self.create_dataset([{"question": "Alpha?"}])
        listed = self.get("/api/v1/evaluations/datasets/").json()["results"]
        self.assertEqual([entry["id"] for entry in listed], [dataset["id"]])
        self.assertEqual(self.delete(f"/api/v1/evaluations/datasets/{dataset['id']}/").status_code, 204)
        self.assertEqual(self.get(f"/api/v1/evaluations/datasets/{dataset['id']}/").status_code, 404)
