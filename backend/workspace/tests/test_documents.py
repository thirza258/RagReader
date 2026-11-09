"""Documents: upload validation, URL/text sources, metadata, reader text, deletion."""
import os
import re
from unittest import mock

from django.core.files.storage import default_storage
from django.test import TransactionTestCase, override_settings

from router.models import Document, Job
from workspace.services import extraction
from workspace.tests.helpers import (
    WorkspaceTestCase, bearer, build_docx, build_pdf, docx_xml, make_user,
)

DOCUMENT_KEYS = {
    "id", "workspace_id", "title", "source_type", "source", "mime_type", "file_size", "has_original_file",
    "status", "status_detail", "progress", "error", "page_count", "chunk_count", "char_count", "index",
    "created_at", "updated_at", "ingested_at",
}


class UploadTests(WorkspaceTestCase):
    def upload_and_queue(self, name, content, **fields):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.upload(name, content, **fields)
        self.assertEqual(response.status_code, 202, response.content)
        return response.json()

    def test_pdf_upload_is_acknowledged_queued_and_then_ingested(self):
        pdf = build_pdf(["Alpha page about embeddings.", "", "Gamma page about reranking."])
        body = self.upload_and_queue("attention.pdf", pdf)
        self.assertEqual(set(body), DOCUMENT_KEYS)
        self.assertEqual((body["status"], body["source_type"], body["source"]), ("QUEUED", "pdf", "attention.pdf"))
        self.assertEqual((body["title"], body["mime_type"], body["file_size"]), ("attention", "application/pdf", len(pdf)))
        self.assertTrue(body["has_original_file"])
        self.assertIsNone(body["index"])
        stored = Document.objects.get(pk=body["id"])
        self.assertRegex(stored.source_path, rf"^documents/user_{self.user.pk}/[0-9a-f]{{32}}/attention\.pdf$")
        job = Job.objects.get(document=stored)
        self.assertEqual((job.kind, job.status), ("ingest", "PENDING"))
        self.delay.assert_called_once_with(str(job.pk))
        # Acknowledging the upload extracted and embedded nothing.
        self.assertEqual(self.embeddings.calls, [])
        self.assertIsNone(stored.extracted_text_path)

        self.assertTrue(self.ingest_last_queued())
        ready = self.get(f"/api/v1/documents/{body['id']}/").json()
        self.assertEqual((ready["status"], ready["progress"], ready["page_count"]), ("READY", 100, 3))
        self.assertIsNotNone(ready["index"])
        self.assertEqual(ready["index"]["method"], "dense")
        self.assertEqual(ready["index"]["embedding_model"], "openai/text-embedding-3-small")
        text = self.get(f"/api/v1/documents/{body['id']}/text/").json()
        self.assertEqual([page["number"] for page in text["pages"]], [1, 3])
        first, third = text["pages"]
        self.assertEqual(text["text"][first["start"]:first["end"]], "Alpha page about embeddings.")
        self.assertEqual(text["text"][third["start"]:third["end"]], "Gamma page about reranking.")
        self.assertEqual((text["char_count"], text["truncated"]), (len(text["text"]), False))

        original = self.get(f"/api/v1/documents/{body['id']}/file/")
        self.assertEqual(original.status_code, 200)
        self.assertEqual(b"".join(original.streaming_content), pdf)
        self.assertEqual(original["Content-Type"], "application/pdf")
        self.assertEqual(original["X-Content-Type-Options"], "nosniff")
        self.assertTrue(original["Content-Disposition"].startswith("inline"))

    def test_docx_built_in_memory_is_accepted_and_extracted(self):
        docx = build_docx(["Alpha heading", "Beta paragraph & more"])
        body = self.upload_and_queue("notes.docx", docx, title="Lab notes")
        self.assertEqual((body["source_type"], body["title"]), ("docx", "Lab notes"))
        self.assertEqual(body["mime_type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertTrue(self.ingest_last_queued())
        text = self.get(f"/api/v1/documents/{body['id']}/text/").json()
        self.assertEqual(text["text"], "Alpha heading\n\nBeta paragraph & more")
        self.assertEqual(text["pages"], [])
        self.assertIsNone(self.get(f"/api/v1/documents/{body['id']}/").json()["page_count"])

    def test_text_and_markdown_files(self):
        for name, content, source_type, mime in (
            ("notes.txt", b"Alpha line one.\nAlpha line two.", "txt", "text/plain"),
            ("readme.md", "# Gamma\n\nCafé notes".encode("utf-8"), "md", "text/markdown"),
            ("legacy.markdown", "Delta in cp1252: ’".encode("cp1252"), "md", "text/markdown"),
        ):
            with self.subTest(name=name):
                body = self.upload_and_queue(name, content)
                self.assertEqual((body["source_type"], body["mime_type"]), (source_type, mime))
                self.assertTrue(self.ingest_last_queued())
                self.assertEqual(self.get(f"/api/v1/documents/{body['id']}/").json()["status"], "READY")

    def test_content_must_match_the_claimed_type(self):
        cases = [
            ("fake.pdf", b"just some text pretending to be a pdf"),
            ("fake.docx", b"PK not really a zip"),
            ("plain.docx", self._zip_without_document()),
            ("binary.txt", b"text\x00with a NUL byte"),
            ("undecodable.md", b"\x81\x8d\x8f\x90\x9d"),
            ("program.exe", b"MZ\x90\x00"),
            ("noextension", b"Alpha"),
        ]
        for name, content in cases:
            with self.subTest(name=name):
                response = self.upload(name, content)
                self.assertEqual(response.status_code, 415, response.content)
                self.assertEqual(response.json()["error"]["code"], "unsupported_file_type")
        self.assertFalse(Document.objects.exists())

    @staticmethod
    def _zip_without_document():
        import io
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("hello.txt", "not a word document")
        return buffer.getvalue()

    @override_settings(MAX_UPLOAD_BYTES=10)
    def test_oversized_files_are_413(self):
        response = self.upload("big.txt", b"Alpha " * 10)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "file_too_large")
        self.assertFalse(Document.objects.exists())

    def test_declared_body_size_is_refused_before_parsing(self):
        with override_settings(MAX_UPLOAD_BYTES=10):
            response = self.client.post(
                "/api/v1/documents/", {"file": ""}, CONTENT_LENGTH=str(5 * 1024 * 1024), **self.auth,
            )
        self.assertEqual(response.status_code, 413)

    def test_missing_and_empty_files_are_validation_errors(self):
        missing = self.client.post("/api/v1/documents/", {"title": "nothing"}, **self.auth)
        self.assertEqual(missing.status_code, 400)
        self.assertIn("file", missing.json()["error"]["details"])
        empty = self.upload("empty.txt", b"")
        self.assertEqual(empty.status_code, 400)

    def test_hostile_filenames_are_sanitised(self):
        body = self.upload_and_queue("../../etc/passwd .txt", b"Alpha")
        stored = Document.objects.get(pk=body["id"])
        self.assertTrue(stored.source_path.startswith(f"documents/user_{self.user.pk}/"))
        self.assertNotIn("..", stored.source_path)
        self.assertEqual(body["source"], "passwd .txt")


class DocxSecurityTests(WorkspaceTestCase):
    def test_xml_with_a_dtd_is_refused_even_when_utf16(self):
        bomb = docx_xml(["Alpha"], prolog='<!DOCTYPE w:document [<!ENTITY a "aaaa">]>')
        for encoded in (bomb.encode("utf-8"), bomb.replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16")):
            with self.subTest(encoding=len(encoded)):
                with self.assertRaises(Exception) as raised:
                    extraction.docx_paragraphs(encoded)
                self.assertEqual(getattr(raised.exception, "code", None), "invalid_docx")

    def test_docx_ingestion_with_a_dtd_fails_cleanly(self):
        docx = build_docx([], document_xml=docx_xml(["Alpha"], prolog='<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'))
        with self.captureOnCommitCallbacks(execute=True):
            body = self.upload("evil.docx", docx).json()
        self.assertFalse(self.ingest_last_queued())
        failed = self.get(f"/api/v1/documents/{body['id']}/").json()
        self.assertEqual(failed["status"], "FAILED")
        self.assertEqual((failed["error"]["code"], failed["error"]["stage"]), ("invalid_docx", "EXTRACTING"))


class UrlAndTextSourceTests(WorkspaceTestCase):
    def test_url_documents_are_queued_without_fetching(self):
        with mock.patch("socket.getaddrinfo", side_effect=AssertionError("no DNS at request time")):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post("/api/v1/documents/", {"source_type": "url", "url": "https://example.com/article"})
        self.assertEqual(response.status_code, 202, response.content)
        body = response.json()
        self.assertEqual((body["source_type"], body["source"], body["title"]), ("url", "https://example.com/article", "https://example.com/article"))
        self.assertFalse(body["has_original_file"])
        self.delay.assert_called_once()

    def test_obviously_unsafe_urls_are_refused_synchronously(self):
        for url in ("http://localhost/admin", "http://127.0.0.1:8080/", "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data",
                    "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://100.64.1.1/", "file:///etc/passwd",
                    "ftp://example.com/file", "http://user:secret@example.com/", "http://example.com:22/", "not a url",
                    "http://2130706433/", "http://0x7f.1/", "http://app.localhost/"):
            with self.subTest(url=url):
                response = self.post("/api/v1/documents/", {"source_type": "url", "url": url})
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(response.json()["error"]["code"], "url_not_allowed")
        self.assertFalse(Document.objects.exists())

    def test_pasted_text(self):
        body = self.add_text("\n\nGamma rays are energetic.\nSecond line.")
        self.assertEqual((body["source_type"], body["source"], body["title"]), ("text", None, "Gamma rays are energetic."))
        self.assertFalse(body["has_original_file"])
        self.assertTrue(self.ingest_last_queued())
        self.assertEqual(self.get(f"/api/v1/documents/{body['id']}/text/").json()["text"], "Gamma rays are energetic. Second line.")
        missing = self.get(f"/api/v1/documents/{body['id']}/file/")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "no_original_file")

    def test_invalid_text_and_unknown_sources(self):
        self.assertEqual(self.post("/api/v1/documents/", {"source_type": "text", "text": "   "}).status_code, 400)
        self.assertEqual(self.post("/api/v1/documents/", {"source_type": "pdf"}).status_code, 400)
        self.assertEqual(self.post("/api/v1/documents/", {}).status_code, 400)
        with override_settings(RAG_MAX_TEXT_CHARS=10):
            response = self.post("/api/v1/documents/", {"source_type": "text", "text": "x" * 11})
        self.assertEqual(response.status_code, 400)
        self.assertIn("text", response.json()["error"]["details"])


class DocumentManagementTests(WorkspaceTestCase):
    def test_list_is_newest_first_and_scoped_to_the_workspace(self):
        first = self.add_text("Alpha one")
        second = self.add_text("Beta two")
        other = self.post("/api/v1/workspaces/", {"name": "Other"}).json()
        self.add_text("Gamma three", workspace_id=other["id"])
        listed = [doc["id"] for doc in self.get("/api/v1/documents/").json()["results"]]
        self.assertEqual(listed, [second["id"], first["id"]])
        self.assertEqual(len(self.get(f"/api/v1/documents/?workspace_id={other['id']}").json()["results"]), 1)
        self.assertEqual(self.get("/api/v1/documents/?workspace_id=999999").status_code, 404)
        self.assertEqual(self.get("/api/v1/documents/?workspace_id=abc").status_code, 404)

    def test_rename(self):
        document = self.add_text("Alpha one")
        renamed = self.patch(f"/api/v1/documents/{document['id']}/", {"title": "  Renamed  "})
        self.assertEqual((renamed.status_code, renamed.json()["title"]), (200, "Renamed"))
        self.assertEqual(self.patch(f"/api/v1/documents/{document['id']}/", {"title": "  "}).status_code, 400)

    def test_delete_removes_files_and_index(self):
        body = self.upload_and_ingest()
        stored = Document.objects.get(pk=body["id"])
        paths = [stored.source_path, stored.extracted_text_path]
        index = stored.current_index.vectorstore_location
        self.assertTrue(all(default_storage.exists(path) for path in paths) and os.path.exists(index))
        with self.captureOnCommitCallbacks(execute=True):
            response = self.delete(f"/api/v1/documents/{body['id']}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Document.objects.filter(pk=body["id"]).exists())
        self.assertFalse(any(default_storage.exists(path) for path in paths))
        self.assertFalse(os.path.exists(index))
        self.assertFalse(os.path.isdir(default_storage.path(os.path.dirname(paths[0]))))
        self.assertEqual(self.get(f"/api/v1/documents/{body['id']}/").status_code, 404)

    def upload_and_ingest(self):
        with self.captureOnCommitCallbacks(execute=True):
            body = self.upload("paper.pdf", build_pdf(["Alpha page.", "Beta page."])).json()
        self.assertTrue(self.ingest_last_queued())
        return body

    def test_text_before_extraction_is_409(self):
        document = self.add_text("Alpha one")
        response = self.get(f"/api/v1/documents/{document['id']}/text/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "ingestion_in_progress")

    def test_unknown_ids_are_json_404s(self):
        for path in ("/api/v1/documents/999999/", "/api/v1/documents/999999/text/", "/api/v1/conversations/999999/"):
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_upload_into_another_owned_workspace(self):
        other = self.post("/api/v1/workspaces/", {"name": "Other"}).json()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.upload("notes.txt", b"Alpha", workspace_id=str(other["id"]))
        self.assertEqual(response.json()["workspace_id"], other["id"])


class QueueFailureTests(TransactionTestCase):
    """The broker being down is a durable, retryable failure, not a lost upload."""

    def test_unreachable_worker_returns_503_with_the_failed_document(self):
        import shutil
        import tempfile
        media = tempfile.mkdtemp(prefix="ragreader-queue-media-")
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        user = make_user("queue")
        with override_settings(MEDIA_ROOT=media), \
                mock.patch("workspace.tasks.ingest_document_task.delay", side_effect=ConnectionError("PRIVATE broker detail")):
            response = self.client.post("/api/v1/documents/", {"source_type": "text", "text": "Alpha"},
                                        content_type="application/json", **bearer(user))
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual((body["error"]["code"], body["error"]["retryable"]), ("job_queue_unavailable", True))
        self.assertNotIn("PRIVATE", response.content.decode())
        self.assertEqual(body["document"]["status"], "FAILED")
        self.assertEqual(body["document"]["error"]["code"], "job_queue_unavailable")
        self.assertEqual(Job.objects.get(document_id=body["document"]["id"]).status, "FAILED")

    def test_unreachable_worker_on_retry_is_503_with_ingestion_status(self):
        import shutil
        import tempfile
        media = tempfile.mkdtemp(prefix="ragreader-queue-media-")
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        user = make_user("retry")
        auth = bearer(user)
        with override_settings(MEDIA_ROOT=media), mock.patch("workspace.tasks.ingest_document_task.delay", side_effect=ConnectionError("down")):
            created = self.client.post("/api/v1/documents/", {"source_type": "text", "text": "Alpha"},
                                       content_type="application/json", **auth).json()["document"]
            retried = self.client.post(f"/api/v1/documents/{created['id']}/ingestion/", **auth)
        self.assertEqual(retried.status_code, 503)
        self.assertEqual(retried.json()["ingestion"]["status"], "FAILED")
        self.assertTrue(retried.json()["ingestion"]["can_retry"])
        self.assertEqual(Job.objects.filter(document_id=created["id"]).count(), 2)
        self.assertTrue(re.match(r"^[0-9a-f-]{36}$", retried.json()["ingestion"]["job"]["id"]))
