"""Convert uploaded document bytes into plain text.

Keeps the rest of the tool-arena stack on its existing
``document_content: str`` contract: callers extract here, then hand the
resulting string to the dispatcher / MCP servers unchanged.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import PurePosixPath


class UnsupportedDocumentType(ValueError):
    """Raised when the file extension has no registered extractor."""


def _extract_docx(data: bytes) -> str:
    from docx import Document

    document = Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


_EXTRACTORS: dict[str, Callable[[bytes], str]] = {
    ".docx": _extract_docx,
    ".pdf": _extract_pdf,
    ".txt": _extract_text,
    ".md": _extract_text,
}

SUPPORTED_EXTENSIONS = frozenset(_EXTRACTORS)


def extract_text(filename: str, data: bytes) -> str:
    suffix = PurePosixPath(filename).suffix.lower()
    extractor = _EXTRACTORS.get(suffix)
    if extractor is None:
        raise UnsupportedDocumentType(
            f"No extractor registered for {suffix!r}"
        )
    return extractor(data)
