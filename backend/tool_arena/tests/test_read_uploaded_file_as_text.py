"""Behavior tests for backend.tool_arena.document.read_uploaded_file_as_text.extract_text."""

from pathlib import Path

import pytest

from backend.tool_arena.document.read_uploaded_file_as_text import (
    UnsupportedDocumentType,
    extract_text,
)

FIXTURES = Path(__file__).parent / "fixtures"
SENTENCE = "The marmot inspects the equifinality of every tool."


def test_extracts_text_from_docx() -> None:
    data = (FIXTURES / "sample.docx").read_bytes()
    text = extract_text("sample.docx", data)
    assert SENTENCE in text


def test_extracts_text_from_pdf() -> None:
    data = (FIXTURES / "sample.pdf").read_bytes()
    text = extract_text("sample.pdf", data)
    assert SENTENCE in text


@pytest.mark.parametrize("name", ["notes.txt", "notes.md", "NOTES.TXT"])
def test_passthrough_for_text(name: str) -> None:
    assert extract_text(name, b"hello world") == "hello world"


def test_unsupported_extension_raises() -> None:
    with pytest.raises(UnsupportedDocumentType):
        extract_text("photo.png", b"\x89PNG\r\n")
