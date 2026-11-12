"""Shared fixtures for the workspace tests.

Hermetic like the rest of the suite: embeddings, LLM calls, Celery and DNS are
replaced at their boundaries while the pipeline, ingestion and chat code run
for real. Not named test_*.py, so the runner does not collect it.
"""
import io
import json
import os
import shutil
import tempfile
import zipfile
from types import SimpleNamespace
from unittest import mock
from xml.sax.saxutils import escape

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

from django.test import TestCase, override_settings

import rag.rag_service as rag_service
from ai_handler.llm import OpenRouterLLM
from pipeline.dense_rag_pipeline import DenseRAGPipeline
from router.models import GuestUser
from workspace.auth import issue_token
from workspace.services import index_cache

LOCMEM_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
KEYWORDS = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")

# Paragraph chunking with paragraphs shorter than half the chunk size gives
# exactly one chunk per paragraph, so "which chunk came back" is meaningful.
CHAT_CONFIG = {
    "llm_model": "openai/gpt-4o-mini",
    "model": "openai/text-embedding-3-small",
    "embedding_model": "openai/text-embedding-3-small",
    "top_k": 5,
    "chunk_strategy": "paragraph",
    "chunk_size": 60,
    "overlap": 0,
    "remove_stop_words": False,
}


def make_user(username="alice"):
    return GuestUser.objects.create(username=username, email=f"{username}@example.com")


def bearer(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token(user)}"}


def keyword_vector(text):
    """One axis per keyword plus a small constant axis (never a zero vector)."""
    lowered = text.lower()
    return [1.0 if word in lowered else 0.0 for word in KEYWORDS] + [0.05]


class FakeEmbeddings:
    """Stand-in for `client.embeddings` that records every provider call."""

    def __init__(self):
        self.calls = []
        self.fail_on_call = None
        self.error = None

    def create(self, input, model=None, **kwargs):  # noqa: A002 - OpenAI kwarg name
        texts = [input] if isinstance(input, str) else list(input)
        self.calls.append(texts)
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise self.error
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=keyword_vector(t)) for i, t in enumerate(texts)])

    @property
    def embedded_texts(self):
        return [text for call in self.calls for text in call]


def chunk(content=None, model="openai/gpt-4o-mini", usage=None):
    choices = [] if content is None else [SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=None)]
    return SimpleNamespace(model=model, choices=choices, usage=usage)


class FakeChat:
    """Stand-in for `client.chat.completions` (streaming answers and rewrites)."""

    def __init__(self, answer="Alpha is the first letter [1].", rewrite="alpha follow up query"):
        self.answer = answer
        self.rewrite = rewrite
        self.calls = []
        self.stream_error = None
        self.served_by = "openai/gpt-4o-mini"

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            if self.stream_error is not None:
                raise self.stream_error
            words = self.answer.split(" ")
            deltas = [word + (" " if i < len(words) - 1 else "") for i, word in enumerate(words)]
            usage = SimpleNamespace(prompt_tokens=50, completion_tokens=len(deltas), total_tokens=50 + len(deltas))
            return iter([chunk(delta, self.served_by) for delta in deltas] + [chunk(None, self.served_by, usage)])
        content = self.rewrite
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    @property
    def stream_calls(self):
        return [call for call in self.calls if call.get("stream")]

    @property
    def rewrite_calls(self):
        return [call for call in self.calls if not call.get("stream")]


def make_chat_pipeline(vector_store_path, embeddings=None, chat=None):
    """A real DenseRAGPipeline whose provider clients are fakes."""
    with override_settings(OPENROUTER_API_KEY="test-key"):
        pipeline = DenseRAGPipeline({**CHAT_CONFIG, "vector_store_path": vector_store_path})
        llm = OpenRouterLLM(model=CHAT_CONFIG["llm_model"], temperature=0.0)
    embeddings = embeddings or FakeEmbeddings()
    chat = chat or FakeChat()
    pipeline.rag.client = SimpleNamespace(embeddings=embeddings)
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=chat))
    pipeline.llm = llm
    return pipeline, embeddings, chat


def build_pdf(pages):
    """A minimal valid PDF with one line of Helvetica text per page."""
    objects = []

    def add(body):
        objects.append(body)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(None)
    pages_id = len(objects)
    kids = []
    for text in pages:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (pages_id, font, content)
        ))
    objects[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % kid for kid in kids), len(kids))
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, xref))
    return out.getvalue()


def docx_xml(paragraphs, prolog=""):
    body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + prolog
        + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        + f"<w:body>{body}</w:body></w:document>"
    )


def build_docx(paragraphs, document_xml=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("word/document.xml", document_xml if document_xml is not None else docx_xml(paragraphs))
    return buffer.getvalue()


def parse_sse(body):
    """[(event, data)] from an event-stream body; `: ping` comments skipped."""
    events = []
    for frame in body.decode("utf-8").split("\n\n"):
        name, data = None, []
        for line in frame.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data.append(line[len("data: "):])
        if name:
            events.append((name, json.loads("\n".join(data))))
    return events


class WorkspaceTestCase(TestCase):
    """Temp media and vector store, a fake-backed chat engine, a signed-in user."""

    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp(prefix="ragreader-workspace-media-")
        self.vector_store = tempfile.mkdtemp(prefix="ragreader-workspace-vs-")
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.vector_store, ignore_errors=True)
        settings_patch = override_settings(MEDIA_ROOT=self.media_root, CACHES=LOCMEM_CACHE)
        settings_patch.enable()
        self.addCleanup(settings_patch.disable)
        # Locmem outlives the override; the sign-in throttle counts in it.
        from django.core.cache import cache
        cache.clear()

        self.pipeline, self.embeddings, self.chat = make_chat_pipeline(self.vector_store)
        engine_patch = mock.patch.object(rag_service.rag_registry, "get_engine", return_value=self.pipeline)
        self.get_engine = engine_patch.start()
        self.addCleanup(engine_patch.stop)

        delay_patch = mock.patch("workspace.tasks.ingest_document_task.delay")
        self.delay = delay_patch.start()
        self.addCleanup(delay_patch.stop)

        index_cache.clear()
        self.addCleanup(index_cache.clear)
        self.user = make_user("alice")
        self.auth = bearer(self.user)

    # ── Requests ────────────────────────────────────────────────────────────
    def get(self, path, auth=None, **extra):
        return self.client.get(path, **(self.auth if auth is None else auth), **extra)

    def post(self, path, data=None, auth=None, **extra):
        return self.client.post(path, data or {}, content_type="application/json", **(self.auth if auth is None else auth), **extra)

    def patch(self, path, data, auth=None):
        return self.client.patch(path, data, content_type="application/json", **(self.auth if auth is None else auth))

    def delete(self, path, auth=None):
        return self.client.delete(path, **(self.auth if auth is None else auth))

    def upload(self, name, content, auth=None, **fields):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post(
            "/api/v1/documents/", {"file": SimpleUploadedFile(name, content), **fields},
            **(self.auth if auth is None else auth),
        )

    # ── Documents ───────────────────────────────────────────────────────────
    def add_text(self, text, title=None, auth=None, **extra):
        payload = {"source_type": "text", "text": text, **extra}
        if title:
            payload["title"] = title
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post("/api/v1/documents/", payload, auth=auth)
        self.assertEqual(response.status_code, 202, response.content)
        return response.json()

    def ingest_last_queued(self):
        """Run the job the last enqueue was given, as the worker would."""
        from workspace.services.ingestion import run_ingestion
        job_id = self.delay.call_args.args[0]
        return run_ingestion(job_id)

    def ready_text_document(self, text, title=None, auth=None):
        document = self.add_text(text, title=title, auth=auth)
        self.assertTrue(self.ingest_last_queued())
        return document
