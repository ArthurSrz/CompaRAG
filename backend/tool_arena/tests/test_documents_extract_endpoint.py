"""Integration tests for POST /tool-arena/documents/extract.

Uses a minimal FastAPI app wired to documents_router only — same isolation
pattern as test_router_documents.py — so we don't pull psycopg2/Redis in
through dispatcher.py.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tool_arena.documents_router import documents_router

FIXTURES = Path(__file__).parent / "fixtures"
SENTENCE = "The marmot inspects the equifinality of every tool."


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(documents_router, prefix="/tool-arena")
    return TestClient(app)


def test_extract_returns_text_for_docx(client: TestClient) -> None:
    data = (FIXTURES / "sample.docx").read_bytes()
    resp = client.post(
        "/tool-arena/documents/extract",
        files={"file": ("sample.docx", data, "application/octet-stream")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert SENTENCE in body["document_content"]
    assert body["char_count"] == len(body["document_content"])


def test_extract_rejects_oversized_binary(client: TestClient) -> None:
    oversized = b"%PDF-1.4\n" + b"\0" * (6 * 1024 * 1024)
    resp = client.post(
        "/tool-arena/documents/extract",
        files={"file": ("big.pdf", oversized, "application/pdf")},
    )
    assert resp.status_code == 413


def test_extract_rejects_oversized_text(client: TestClient) -> None:
    oversized = b"a" * (600 * 1024)
    resp = client.post(
        "/tool-arena/documents/extract",
        files={"file": ("big.txt", oversized, "text/plain")},
    )
    assert resp.status_code == 413


def test_extract_rejects_unsupported_extension(client: TestClient) -> None:
    resp = client.post(
        "/tool-arena/documents/extract",
        files={"file": ("photo.png", b"\x89PNG\r\n", "image/png")},
    )
    assert resp.status_code == 415
