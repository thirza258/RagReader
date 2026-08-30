import io
import os

import re
import requests
from typing import Union
from bs4 import BeautifulSoup
import PyPDF2

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from utils.helper import _document_base_path
from django.utils.text import get_valid_filename

class DataLoader:
    """
    Django-integrated loader that:
    - Saves source files into MEDIA_ROOT
    - Extracts clean text (supporting PDF, TXT, and Markdown)
    - Returns (text, stored_paths)
    """

    @staticmethod
    def process_input(
        source: Union[str, UploadedFile],
        username: str
    ) -> dict:
        """
        Returns:
        {
            "user": str,
            "text": str,
            "source_path": str,
            "text_path": str,
            "filename": str,
            "source_type": str
        }
        """

        base_path = _document_base_path(username)

        # ---------- File Upload (PDF, TXT, MD) ----------
        if isinstance(source, UploadedFile):
            filename = get_valid_filename(source.name)
            # Storage may rename on collision — always use the returned path.
            saved_path = default_storage.save(f"{base_path}/{filename}", source)
            ext = os.path.splitext(filename)[1].lower()

            if ext == ".pdf":
                text = DataLoader._parse_pdf(saved_path)
                source_type = "pdf"
            elif ext in [".txt", ".text"]:
                text = DataLoader._parse_txt(saved_path)
                source_type = "txt"
            elif ext in [".md", ".markdown"]:
                text = DataLoader._parse_markdown(saved_path)
                source_type = "md"
            else:
                raise ValueError(
                    f"Unsupported file format '{ext}'. Supported formats are: PDF (.pdf), Text (.txt), and Markdown (.md)."
                )

            text_path = DataLoader._save_text(base_path, text)

            return {
                "user": username,
                "text": text,
                "source_path": saved_path,
                "text_path": text_path,
                "filename": filename,   
                "source_type": source_type,
            }

        # ---------- URL ----------
        if isinstance(source, str) and source.startswith(("http://", "https://")):
            html = DataLoader._fetch_url(source)

            html_path = default_storage.save(f"{base_path}/source.html", ContentFile(html))

            text = DataLoader._extract_text_from_html(html)
            text_path = DataLoader._save_text(base_path, text)

            return {
                "user": username,
                "text": text,
                "name": source,
                "source_path": html_path,
                "text_path": text_path,
                "source_type": "url",
            }

        # ---------- Local File Paths ----------
        if isinstance(source, str) and source.lower().endswith(".pdf"):
            text = DataLoader._parse_pdf(source)
            text_path = DataLoader._save_text(base_path, text)

            return {
                "user": username,
                "text": text,
                "source_path": source,
                "text_path": text_path,
                "source_type": "pdf",
            }

        if isinstance(source, str) and source.lower().endswith((".txt", ".text")) and (os.path.exists(source) or default_storage.exists(source)):
            text = DataLoader._parse_txt(source)
            text_path = DataLoader._save_text(base_path, text)

            return {
                "user": username,
                "text": text,
                "source_path": source,
                "text_path": text_path,
                "source_type": "txt",
            }

        if isinstance(source, str) and source.lower().endswith((".md", ".markdown")) and (os.path.exists(source) or default_storage.exists(source)):
            text = DataLoader._parse_markdown(source)
            text_path = DataLoader._save_text(base_path, text)

            return {
                "user": username,
                "text": text,
                "source_path": source,
                "text_path": text_path,
                "source_type": "md",
            }

        # ---------- Raw Text ----------
        text = source if isinstance(source, str) else ""
        text_path = DataLoader._save_text(base_path, text)

        return {
            "user": username,
            "text": text,
            "name": "text",
            "source_path": None,
            "text_path": text_path,
            "source_type": "text",
        }

    @staticmethod
    def _parse_pdf(source: Union[str, UploadedFile, io.BytesIO]) -> str:
        text_content = []
        if isinstance(source, str):
            if default_storage.exists(source):
                with default_storage.open(source, "rb") as f:
                    reader = PyPDF2.PdfReader(io.BytesIO(f.read()))
            elif os.path.exists(source):
                reader = PyPDF2.PdfReader(source)
            else:
                raise FileNotFoundError(f"PDF file not found: {source}")
        elif hasattr(source, "read"):
            reader = PyPDF2.PdfReader(source)
        else:
            raise ValueError("Unsupported source type for PDF parsing.")

        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_content.append(text)

        return DataLoader._clean_text("\n".join(text_content))

    @staticmethod
    def _read_file_text(source: Union[str, UploadedFile, io.BytesIO]) -> str:
        if isinstance(source, str):
            if default_storage.exists(source):
                with default_storage.open(source, "rb") as f:
                    raw = f.read()
            elif os.path.exists(source):
                with open(source, "rb") as f:
                    raw = f.read()
            else:
                raise FileNotFoundError(f"File not found: {source}")
        elif hasattr(source, "read"):
            raw = source.read()
            if hasattr(source, "seek"):
                source.seek(0)
            if isinstance(raw, str):
                return raw
        else:
            raise ValueError("Unsupported source type for text reading.")

        for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _parse_txt(source: Union[str, UploadedFile, io.BytesIO]) -> str:
        raw_text = DataLoader._read_file_text(source)
        return DataLoader._clean_text(raw_text)

    @staticmethod
    def _parse_markdown(source: Union[str, UploadedFile, io.BytesIO]) -> str:
        raw_text = DataLoader._read_file_text(source)
        return DataLoader._clean_text(raw_text)

    @staticmethod
    def _fetch_url(url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _extract_text_from_html(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return DataLoader._clean_text(soup.get_text(separator=" "))

    @staticmethod
    def _save_text(base_path: str, text: str) -> str:
        # Storage may rename on collision — return the actual saved path.
        return default_storage.save(f"{base_path}/extracted.txt", ContentFile(text))

    @staticmethod
    def _clean_text(text: str) -> str:
        # Replace single newlines between words with space
        text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)

        # Collapse multiple newlines into paragraph break
        text = re.sub(r"\n{2,}", "\n\n", text)

        # Normalize spaces
        text = re.sub(r"[ \t]+", " ", text)

        return text.strip()
    
    def load(self, path: str) -> str:
        """
        Simple loader to extract text from a given file path.
        Supports PDF, TXT, and Markdown files.
        """
        lower = path.lower()
        if lower.endswith(".pdf"):
            return self._parse_pdf(path)
        elif lower.endswith((".txt", ".text", ".md", ".markdown")):
            if default_storage.exists(path):
                with default_storage.open(path, "rb") as f:
                    raw = f.read()
            elif os.path.exists(path):
                with open(path, "rb") as f:
                    raw = f.read()
            else:
                raise FileNotFoundError(f"File not found: {path}")

            for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")
        else:
            raise ValueError("Unsupported file type for loading.")

_loader = None

def get_loader():
    global _loader
    if _loader is None:
        _loader = DataLoader()
    return _loader