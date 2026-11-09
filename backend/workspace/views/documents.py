import os

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from router.models import Document
from workspace.errors import ApiError, error_response
from workspace.serializers import (
    DocumentPatchInput, TERMINAL_STATUSES, TextDocumentInput, UrlDocumentInput,
    document_payload, has_original_file, ingestion_payload, validated,
)
from workspace.services.documents import create_document, delete_documents
from workspace.services.extraction import read_stored
from workspace.services.ingestion import latest_job, live_job, queue_ingestion, refresh_document_status
from workspace.services.uploads import (
    delete_storage_path, document_directory, store_bytes, store_upload, too_large, validate_upload,
)
from workspace.services.url_fetch import validate_url
from workspace.views.base import OwnedAPIView

TAGS = ["Documents"]
# Multipart framing and the other form fields on top of the file itself.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024
TEXT_ENDPOINT_MAX_CHARS = 5_000_000
TITLE_FROM_TEXT_CHARS = 80
WORKSPACE_PARAM = OpenApiParameter("workspace_id", OpenApiTypes.INT, description="Defaults to the user's default workspace.")


def invalid(field, message):
    return ApiError("invalid_request", "The request contains invalid or missing fields.", details={field: [message]})


def title_from_filename(filename):
    stem = os.path.splitext(filename)[0].strip()
    return stem or filename or "Untitled document"


def title_from_text(text):
    for line in text.splitlines():
        line = " ".join(line.split())
        if line:
            return line if len(line) <= TITLE_FROM_TEXT_CHARS else line[:TITLE_FROM_TEXT_CHARS - 1].rstrip() + "…"
    return "Pasted text"


def created_response(document, failures):
    if failures:
        failure = failures[0]
        return error_response(failure.code, str(failure), status=503, retryable=True,
                              extra={"document": document_payload(document)})
    return Response(document_payload(document), status=202)


class DocumentListView(OwnedAPIView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(tags=TAGS, operation_id="documents_list", summary="List documents, newest first", parameters=[WORKSPACE_PARAM], responses=OpenApiTypes.OBJECT)
    def get(self, request):
        workspace = self.resolve_workspace(request.query_params.get("workspace_id"))
        documents = (
            Document.objects.filter(user=request.user, workspace=workspace)
            .select_related("current_index").order_by("-created_at", "-id")
        )
        return Response({"results": [document_payload(refresh_document_status(document)) for document in documents]})

    @extend_schema(
        tags=TAGS, operation_id="documents_create",
        summary="Add a document: multipart `file`, or JSON {source_type: url|text}",
        request={"multipart/form-data": OpenApiTypes.OBJECT, "application/json": OpenApiTypes.OBJECT},
        responses={202: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        if (request.content_type or "").startswith("multipart/"):
            return self._create_from_upload(request)
        data = request.data if hasattr(request.data, "get") else {}
        source_type = data.get("source_type")
        if source_type == "url":
            return self._create_from_url(request, data)
        if source_type == "text":
            return self._create_from_text(request, data)
        raise invalid("source_type", 'Upload a file as multipart/form-data, or send JSON with source_type "url" or "text".')

    def _create_from_upload(self, request):
        # Refuse an oversized body before it is parsed into an upload (under
        # WSGI before it is read at all; under ASGI the server has already
        # buffered it, but nothing is written to storage).
        declared = request.META.get("CONTENT_LENGTH") or ""
        if declared.isdigit() and int(declared) > settings.MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES:
            raise too_large(settings.MAX_UPLOAD_BYTES)
        uploaded = request.FILES.get("file")
        if uploaded is None:
            raise invalid("file", "Attach the document as the 'file' field.")
        title = (request.data.get("title") or "").strip()
        if len(title) > 255:
            raise invalid("title", "Ensure this field has no more than 255 characters.")
        workspace = self.resolve_workspace(request.data.get("workspace_id"))
        upload = validate_upload(uploaded)
        path = store_upload(request.user, uploaded, upload.filename)
        try:
            document, failures = create_document(
                user=request.user, workspace=workspace,
                name=title or title_from_filename(upload.original_filename),
                source_type=upload.source_type, source_path=path,
                mime_type=upload.mime_type, file_size=upload.size,
                metadata={"original_filename": upload.original_filename},
            )
        except Exception:
            delete_storage_path(path)
            raise
        return created_response(document, failures)

    def _create_from_url(self, request, data):
        values = validated(UrlDocumentInput, data)
        workspace = self.resolve_workspace(values.get("workspace_id"))
        url = values["url"].strip()
        # Obvious refusals (scheme, localhost, private literals) answer now;
        # the worker re-checks every resolved address at connect time.
        validate_url(url)
        title = (values.get("title") or "").strip()
        document, failures = create_document(
            user=request.user, workspace=workspace, name=title or url, source_type="url",
            source_url=url, metadata={"auto_title": not title},
        )
        return created_response(document, failures)

    def _create_from_text(self, request, data):
        values = validated(TextDocumentInput, data)
        text = values["text"]
        if not text.strip():
            raise invalid("text", "This field may not be blank.")
        limit = settings.RAG_MAX_TEXT_CHARS
        if len(text) > limit:
            raise invalid("text", f"Text is longer than the {limit:,}-character limit.")
        workspace = self.resolve_workspace(values.get("workspace_id"))
        encoded = text.encode("utf-8")
        path = store_bytes(document_directory(request.user), "pasted.txt", encoded)
        try:
            document, failures = create_document(
                user=request.user, workspace=workspace,
                name=(values.get("title") or "").strip() or title_from_text(text),
                source_type="text", source_path=path, mime_type="text/plain", file_size=len(encoded),
            )
        except Exception:
            delete_storage_path(path)
            raise
        return created_response(document, failures)


class DocumentDetailView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="documents_retrieve", summary="Get a document's metadata and status", responses=OpenApiTypes.OBJECT)
    def get(self, request, document_id):
        return Response(document_payload(refresh_document_status(self.get_document(document_id))))

    @extend_schema(tags=TAGS, operation_id="documents_partial_update", summary="Rename a document", request=DocumentPatchInput, responses=OpenApiTypes.OBJECT)
    def patch(self, request, document_id):
        document = self.get_document(document_id)
        title = validated(DocumentPatchInput, request.data)["title"].strip()
        if not title:
            raise invalid("title", "This field may not be blank.")
        document.name = title
        document.save(update_fields=["name", "updated_at"])
        return Response(document_payload(refresh_document_status(document)))

    @extend_schema(tags=TAGS, operation_id="documents_destroy", summary="Delete a document, its files and its indexes", responses={204: None})
    def delete(self, request, document_id):
        document = self.get_document(document_id)
        with transaction.atomic():
            delete_documents([document])
        return Response(status=204)


class DocumentIngestionView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="documents_ingestion_retrieve", summary="Ingestion status and stage checklist", responses=OpenApiTypes.OBJECT)
    def get(self, request, document_id):
        document = refresh_document_status(self.get_document(document_id))
        live = live_job(document)
        return Response(ingestion_payload(document, live or latest_job(document), can_retry=live is None))

    @extend_schema(tags=TAGS, operation_id="documents_ingestion_create", summary="Retry or re-index (409 while a run is in progress)", request=None, responses={202: OpenApiTypes.OBJECT})
    def post(self, request, document_id):
        document = refresh_document_status(self.get_document(document_id))
        failures = []
        with transaction.atomic():
            # Serialises double-clicks (row lock on PostgreSQL).
            Document.objects.select_for_update().filter(pk=document.pk).first()
            if live_job(document) is not None:
                raise ApiError("ingestion_in_progress", "This document is already being ingested. Wait for the current run to finish.",
                               status=409, retryable=True)
            job = queue_ingestion(document, failures)
        document.refresh_from_db()
        job.refresh_from_db()
        payload = ingestion_payload(document, job, can_retry=bool(failures))
        if failures:
            return error_response(failures[0].code, str(failures[0]), status=503, retryable=True, extra={"ingestion": payload})
        return Response(payload, status=202)


class DocumentFileView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="documents_file_retrieve", summary="The original uploaded file (PDF, DOCX, TXT, Markdown)", responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    def get(self, request, document_id):
        document = self.get_document(document_id)
        if not has_original_file(document):
            raise ApiError("no_original_file", "This document has no original file. Web pages and pasted text are available as text.", status=404)
        try:
            handle = default_storage.open(document.source_path, "rb")
        except (FileNotFoundError, SuspiciousFileOperation, OSError, ValueError):
            raise ApiError("no_original_file", "The original file is no longer stored.", status=404)
        filename = (document.metadata or {}).get("original_filename") or os.path.basename(document.source_path)
        response = FileResponse(handle, content_type=document_payload(document)["mime_type"] or "application/octet-stream",
                                as_attachment=False, filename=filename)
        response["X-Content-Type-Options"] = "nosniff"
        return response


class DocumentTextView(OwnedAPIView):
    @extend_schema(tags=TAGS, operation_id="documents_text_retrieve", summary="Extracted text with page offsets, for the reader", responses=OpenApiTypes.OBJECT)
    def get(self, request, document_id):
        document = refresh_document_status(self.get_document(document_id))
        data = read_stored(document.extracted_text_path)
        if data is None:
            if document.status not in TERMINAL_STATUSES:
                raise ApiError("ingestion_in_progress", "The text is available once extraction has finished.", status=409, retryable=True)
            raise ApiError("text_unavailable", "This document has no extracted text. Re-index it to extract the text again.", status=404)
        text = data.decode("utf-8", errors="replace")
        truncated = len(text) > TEXT_ENDPOINT_MAX_CHARS
        return Response({
            "document_id": document.pk,
            "text": text[:TEXT_ENDPOINT_MAX_CHARS] if truncated else text,
            "pages": (document.metadata or {}).get("pages") or [],
            "char_count": len(text),
            "truncated": truncated,
        })
