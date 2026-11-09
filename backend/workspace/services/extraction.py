"""Per-source text extraction and cleaning (ingestion stages EXTRACTING, CLEANING).

Extraction keeps page boundaries for PDFs so every chunk can later be mapped
to the page it came from; the other formats are a single "page". Cleaning
reuses `DataLoader._clean_text`, the same normalisation the legacy upload
path applies, so a document reads the same whichever way it arrived.
"""
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from xml.parsers import expat

import PyPDF2
from bs4 import BeautifulSoup
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import default_storage

from common.errors import PipelineError
from utils.insert_file import DataLoader
from workspace.services import url_fetch
from workspace.services.uploads import (
    DOCX_MAIN_PART, DOCX_MAX_RATIO, DOCX_MAX_XML_BYTES, check_docx, decode_text,
    document_directory, store_bytes,
)

logger = logging.getLogger(__name__)

# expat reports namespaced names as "<uri>}<local>" with this separator.
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# Elements whose text is navigation or chrome rather than the article.
HTML_NOISE = ["script", "style", "noscript", "template", "svg", "canvas", "iframe",
              "nav", "header", "footer", "aside", "form", "button", "select", "dialog"]
HTML_BLOCKS = ["p", "div", "section", "article", "main", "li", "ul", "ol", "dl", "dt", "dd",
               "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "table", "tr",
               "figcaption", "br", "hr"]
STORED_PAGE_NAMES = {"pdf": "source.pdf", "html": "source.html", "text": "source.txt"}


@dataclass
class Extracted:
    pages: list            # [(page_number, raw text)]
    paged: bool            # True when page numbers are real (PDF content)
    page_count: int | None = None
    title: str | None = None
    document_updates: dict = field(default_factory=dict)
    metadata_updates: dict = field(default_factory=dict)


@dataclass
class CleanText:
    text: str
    pages: list            # [{"number", "start", "end"}], end exclusive


def no_text_error():
    return PipelineError(
        "no_extractable_text",
        "No readable text was found in this document. Scanned PDFs need OCR, which is not supported yet.",
        http_status=422,
    )


def read_stored(path):
    """Bytes of a storage-relative path. Never reads outside MEDIA_ROOT."""
    if not path:
        return None
    try:
        if not default_storage.exists(path):
            return None
        with default_storage.open(path, "rb") as handle:
            return handle.read()
    except (SuspiciousFileOperation, OSError, ValueError):
        logger.warning("Stored file %s could not be read", path, exc_info=True)
        return None


# ── Formats ──────────────────────────────────────────────────────────────────

def extract_pdf(data: bytes) -> Extracted:
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception:
                unlocked = 0
            if not unlocked:
                raise PipelineError("pdf_encrypted", "This PDF is password-protected. Remove the password and upload it again.", http_status=422)
        pages = list(reader.pages)
    except PipelineError:
        raise
    except Exception as exc:
        raise PipelineError("invalid_pdf", "The PDF could not be read. It may be damaged.", http_status=422) from exc
    extracted = []
    for number, page in enumerate(pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            # One undecodable page should not cost the reader the rest.
            logger.warning("Text extraction failed on PDF page %s", number, exc_info=True)
            text = ""
        extracted.append((number, text))
    return Extracted(pages=extracted, paged=True, page_count=len(pages))


def extract_docx(data: bytes) -> Extracted:
    archive_file = io.BytesIO(data)
    check_docx(archive_file)
    with zipfile.ZipFile(archive_file) as archive:
        info = archive.getinfo(DOCX_MAIN_PART)
        if info.file_size > DOCX_MAX_XML_BYTES or (
            info.compress_size and info.file_size / info.compress_size > DOCX_MAX_RATIO
        ):
            raise PipelineError("invalid_docx", "The DOCX file expands to more data than a normal document.", http_status=422)
        with archive.open(info) as handle:
            xml = handle.read(DOCX_MAX_XML_BYTES + 1)
    if len(xml) > DOCX_MAX_XML_BYTES:
        raise PipelineError("invalid_docx", "The DOCX file expands to more data than a normal document.", http_status=422)
    return Extracted(pages=[(1, "\n\n".join(docx_paragraphs(xml)))], paged=False)


def _refuse_dtd(*_args):
    # Word never writes a DTD or entity declarations; one here can only be an
    # entity-expansion or external-entity attack. Refusing them in the parser
    # (rather than searching the bytes) also covers UTF-16 encoded XML.
    raise PipelineError("invalid_docx", "The DOCX file contains unsupported XML.", http_status=422)


def docx_paragraphs(xml: bytes):
    """Paragraph texts of word/document.xml, streamed through expat."""
    parser = expat.ParserCreate(namespace_separator="}")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = _refuse_dtd
    parser.EntityDeclHandler = _refuse_dtd
    parser.ExternalEntityRefHandler = _refuse_dtd
    paragraph, text, tab, breaks = WORD_NS + "p", WORD_NS + "t", WORD_NS + "tab", (WORD_NS + "br", WORD_NS + "cr")
    # A stack because text boxes nest paragraphs inside paragraphs.
    open_paragraphs, paragraphs, in_text = [], [], [False]

    def start(name, _attrs):
        if name == paragraph:
            open_paragraphs.append([])
        elif name == text:
            in_text[0] = True
        elif open_paragraphs and name == tab:
            open_paragraphs[-1].append("\t")
        elif open_paragraphs and name in breaks:
            open_paragraphs[-1].append("\n")

    def end(name):
        if name == text:
            in_text[0] = False
        elif name == paragraph and open_paragraphs:
            content = "".join(open_paragraphs.pop()).strip()
            if content:
                paragraphs.append(content)

    def characters(data):
        if in_text[0] and open_paragraphs:
            open_paragraphs[-1].append(data)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters
    try:
        parser.Parse(xml, True)
    except expat.ExpatError as exc:
        raise PipelineError("invalid_docx", "The DOCX file could not be read. It may be damaged.", http_status=422) from exc
    return paragraphs


def extract_plain(data: bytes) -> Extracted:
    text = decode_text(data)
    if text is None:
        raise PipelineError("unsupported_file_type", "The file is not a readable text file.", http_status=415)
    return Extracted(pages=[(1, text)], paged=False)


def extract_html(data: bytes, charset=None) -> Extracted:
    soup = BeautifulSoup(data, "html.parser", from_encoding=charset)
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    for tag in soup(HTML_NOISE):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    # Block boundaries become paragraph breaks, which _clean_text keeps;
    # everything else collapses to spaces.
    for tag in root.find_all(HTML_BLOCKS):
        tag.insert_before("\n\n")
        tag.insert_after("\n\n")
    text = root.get_text("")
    return Extracted(pages=[(1, text)], paged=False, title=title or None)


# ── Documents ────────────────────────────────────────────────────────────────

def _extract_url(document) -> Extracted:
    metadata = document.metadata or {}
    stored = read_stored(document.source_path)
    if stored is not None:
        # Re-indexing reads the saved copy and never refetches: the index then
        # matches what the user saw when the document was added.
        kind = metadata.get("content_kind")
        if kind is None:
            kind = url_fetch.CONTENT_TYPES.get(metadata.get("content_type") or "", None) or (
                "pdf" if stored[:1024].find(b"%PDF-") != -1 else "html"
            )
        return _extract_kind(kind, stored, metadata.get("charset"))

    if not document.source_url:
        raise PipelineError("missing_source", "This web page has no saved copy or URL to fetch. Add it again.", http_status=409)
    result = url_fetch.fetch_url(document.source_url)
    directory = document_directory(document.user)
    path = store_bytes(directory, STORED_PAGE_NAMES[result.kind], result.body)
    extracted = _extract_kind(result.kind, result.body, result.charset)
    extracted.document_updates.update({
        "source_path": path,
        "mime_type": result.content_type[:100],
        "file_size": len(result.body),
    })
    extracted.metadata_updates.update({
        "final_url": result.final_url,
        "content_type": result.content_type,
        "content_kind": result.kind,
        "charset": result.charset,
    })
    return extracted


def _extract_kind(kind, data, charset=None) -> Extracted:
    if kind == "pdf":
        return extract_pdf(data)
    if kind == "html":
        return extract_html(data, charset)
    return extract_plain(data)


def extract_document(document) -> Extracted:
    source_type = document.source_type
    if source_type == "url":
        return _extract_url(document)
    data = read_stored(document.source_path)
    if data is None and source_type in ("text", "txt", "md", "markdown"):
        # Legacy pasted text was only ever saved as extracted text.
        data = read_stored(document.extracted_text_path)
    if data is None:
        raise PipelineError("missing_source", "The original file is no longer stored. Upload the document again.", http_status=409)
    if source_type == "pdf":
        return extract_pdf(data)
    if source_type == "docx":
        return extract_docx(data)
    if source_type in ("txt", "md", "markdown", "text"):
        return extract_plain(data)
    raise PipelineError("unsupported_file_type", f"Documents of type '{source_type}' cannot be ingested.", http_status=415)


def clean_pages(extracted: Extracted) -> CleanText:
    """Clean each page, drop empty ones, join with blank lines and record where
    each page's text starts and ends in the joined text."""
    parts, pages, cursor = [], [], 0
    for number, raw in extracted.pages:
        cleaned = DataLoader._clean_text(raw or "")
        if not cleaned:
            continue
        if parts:
            cursor += 2  # the "\n\n" joiner
        pages.append({"number": number, "start": cursor, "end": cursor + len(cleaned)})
        parts.append(cleaned)
        cursor += len(cleaned)
    return CleanText(text="\n\n".join(parts), pages=pages)


def count_words(text):
    return len(re.findall(r"\S+", text))
