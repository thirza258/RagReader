"""Upload validation, content sniffing and storage (PRD §39 "File security").

The type of a file is decided by its bytes, not by the browser's
Content-Type: the extension says what the file claims to be, and the content
has to agree. Nothing here parses a document fully — that is the worker's job
— so acknowledging an upload stays fast.
"""
import logging
import os
import uuid
import zipfile
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename

from workspace.errors import ApiError

logger = logging.getLogger(__name__)

EXTENSIONS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".text": "txt",
    ".md": "md",
    ".markdown": "md",
}
MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
}
UNSUPPORTED_MESSAGE = "Upload a PDF, DOCX, TXT or Markdown file."

# Zip-bomb guards. A real .docx is a few hundred entries and its main XML part
# rarely exceeds a few MB; these leave generous headroom.
DOCX_MAX_ENTRIES = 5000
DOCX_MAX_TOTAL_BYTES = 512 * 1024 * 1024
DOCX_MAX_XML_BYTES = 64 * 1024 * 1024
DOCX_MAX_RATIO = 200
DOCX_MAIN_PART = "word/document.xml"

MAX_FILENAME_LENGTH = 120


@dataclass
class ValidatedUpload:
    source_type: str
    mime_type: str
    size: int
    original_filename: str
    filename: str


def unsupported(message=UNSUPPORTED_MESSAGE):
    return ApiError("unsupported_file_type", message, status=415)


def too_large(limit, noun="file"):
    megabytes = limit / (1024 * 1024)
    shown = f"{megabytes:.0f} MB" if megabytes >= 1 else f"{limit:,} bytes"
    return ApiError("file_too_large", f"The {noun} is larger than the {shown} limit.", status=413)


def sanitized_filename(original, source_type):
    """A storage-safe name that keeps the original's readable stem and extension."""
    stem, ext = os.path.splitext(os.path.basename(original or ""))
    ext = ext.lower() if ext.lower() in EXTENSIONS else "." + source_type
    try:
        stem = get_valid_filename(stem)
    except SuspiciousFileOperation:
        stem = ""
    stem = stem.strip("._")[: MAX_FILENAME_LENGTH - len(ext)] or "document"
    return stem + ext


def _read_head(uploaded, size=8192):
    uploaded.seek(0)
    head = uploaded.read(size)
    uploaded.seek(0)
    return head


def decode_text(data: bytes):
    """Text decoding shared by validation and extraction; None when not text."""
    if b"\x00" in data:
        return None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def check_docx(fileobj):
    """Raise unless `fileobj` is a zip with a sane-sized word/document.xml."""
    try:
        with zipfile.ZipFile(fileobj) as archive:
            entries = archive.infolist()
            if len(entries) > DOCX_MAX_ENTRIES:
                raise unsupported("The DOCX file has too many parts to be a normal document.")
            if sum(entry.file_size for entry in entries) > DOCX_MAX_TOTAL_BYTES:
                raise unsupported("The DOCX file expands to more data than a normal document.")
            main = next((entry for entry in entries if entry.filename == DOCX_MAIN_PART), None)
            if main is None:
                raise unsupported("The file is not a Word document (word/document.xml is missing).")
            if main.file_size > DOCX_MAX_XML_BYTES or (
                main.compress_size and main.file_size / main.compress_size > DOCX_MAX_RATIO
            ):
                raise unsupported("The DOCX file expands to more data than a normal document.")
    except zipfile.BadZipFile:
        raise unsupported("The file is not a valid DOCX document.")
    finally:
        if hasattr(fileobj, "seek"):
            fileobj.seek(0)


def validate_upload(uploaded) -> ValidatedUpload:
    original = os.path.basename(getattr(uploaded, "name", "") or "")
    source_type = EXTENSIONS.get(os.path.splitext(original)[1].lower())
    if source_type is None:
        raise unsupported()
    limit = settings.MAX_UPLOAD_BYTES
    size = uploaded.size or 0
    if size > limit:
        raise too_large(limit)
    if size == 0:
        raise ApiError("invalid_request", "The request contains invalid or missing fields.",
                       details={"file": ["The file is empty."]})

    if source_type == "pdf":
        # The PDF spec puts the header first; readers tolerate up to 1 KB of junk.
        if b"%PDF-" not in _read_head(uploaded, 1024):
            raise unsupported("The file is not a valid PDF.")
    elif source_type == "docx":
        check_docx(uploaded)
    else:
        uploaded.seek(0)
        data = uploaded.read()
        uploaded.seek(0)
        if decode_text(data) is None:
            raise unsupported("The file is not a readable text file.")

    return ValidatedUpload(
        source_type=source_type,
        mime_type=MIME_TYPES[source_type],
        size=size,
        original_filename=original[:255],
        filename=sanitized_filename(original, source_type),
    )


def document_directory(user):
    """documents/user_<user id>/<uuid>: one private directory per document."""
    return f"documents/user_{user.pk}/{uuid.uuid4().hex}"


def store_upload(user, uploaded, filename):
    return default_storage.save(f"{document_directory(user)}/{filename}", uploaded)


def store_bytes(directory, filename, data: bytes):
    return default_storage.save(f"{directory}/{filename}", ContentFile(data))


def directory_of(path):
    return os.path.dirname(path) if path else None


# ── Cleanup ──────────────────────────────────────────────────────────────────

def delete_storage_path(path):
    if not path:
        return
    try:
        if default_storage.exists(path):
            default_storage.delete(path)
    except (SuspiciousFileOperation, OSError, ValueError):
        # Legacy rows may hold paths outside MEDIA_ROOT; those are never ours
        # to delete.
        logger.warning("Could not delete stored file %s", path, exc_info=True)


def _remove_empty_directory(directory):
    if not directory:
        return
    try:
        absolute = default_storage.path(directory)
        if os.path.isdir(absolute) and not os.listdir(absolute):
            os.rmdir(absolute)
    except (SuspiciousFileOperation, NotImplementedError, OSError):
        pass


def delete_index_file(location, base_path):
    """Delete an index pickle, but only from inside its vector store."""
    if not location or not base_path:
        return
    try:
        root = os.path.realpath(base_path)
        target = os.path.realpath(location)
        if os.path.commonpath([root, target]) != root or target == root:
            logger.warning("Refusing to delete index outside its vector store: %s", location)
            return
        if os.path.isfile(target):
            os.remove(target)
    except (OSError, ValueError):
        logger.warning("Could not delete index file %s", location, exc_info=True)


def delete_document_files(paths, index_files):
    """Remove a deleted document's stored files and index pickles.

    `paths` are storage-relative (original upload, saved page, extracted text);
    `index_files` are (location, vector store root) pairs.
    """
    directories = set()
    for path in paths:
        delete_storage_path(path)
        directories.add(directory_of(path))
    for directory in directories:
        _remove_empty_directory(directory)
    for location, base_path in index_files:
        delete_index_file(location, base_path)
