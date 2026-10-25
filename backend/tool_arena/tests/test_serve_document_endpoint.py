"""Endpoint tests for document library routes (DOC-02, DOC-03).

Tests exercise the REAL router imported from backend.tool_arena.router,
mounted on a minimal FastAPI app to avoid pulling in the full backend
(DB/Redis) dependency chain.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tool_arena.document.serve_document_endpoint import documents_router as router

_EXPECTED_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"
_EXPECTED_IDS = {"rag_overview", "langchain_concepts", "llamaindex_concepts"}


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(router, prefix="/tool-arena")
    return TestClient(app)


def test_list_documents_returns_200_with_all_ids(client):
    resp = client.get("/tool-arena/documents")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    ids = {item["id"] for item in body}
    assert _EXPECTED_IDS.issubset(ids), f"missing ids: {_EXPECTED_IDS - ids}"
    for item in body:
        assert set(item.keys()) == {
            "id",
            "title",
            "description",
            "suggested_question",
            "expected_answer",
        }


def test_list_documents_has_no_content_field(client):
    resp = client.get("/tool-arena/documents")
    assert resp.status_code == 200
    for item in resp.json():
        assert "content" not in item


def test_list_documents_has_cache_control(client):
    resp = client.get("/tool-arena/documents")
    assert resp.headers.get("Cache-Control") == _EXPECTED_CACHE_CONTROL


def test_get_document_returns_200_with_content(client):
    resp = client.get("/tool-arena/documents/rag_overview")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "id",
        "title",
        "description",
        "content",
        "suggested_question",
        "expected_answer",
    }
    assert body["id"] == "rag_overview"
    assert isinstance(body["content"], str)
    assert len(body["content"]) > 0
    assert "RAG" in body["content"]


def test_get_document_has_cache_control(client):
    resp = client.get("/tool-arena/documents/rag_overview")
    assert resp.headers.get("Cache-Control") == _EXPECTED_CACHE_CONTROL


def test_get_unknown_document_returns_404(client):
    resp = client.get("/tool-arena/documents/does_not_exist")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Document not found"}


def test_endpoints_require_no_auth(client):
    # No Authorization header sent; both endpoints must still succeed.
    list_resp = client.get("/tool-arena/documents")
    detail_resp = client.get("/tool-arena/documents/rag_overview")
    assert list_resp.status_code == 200
    assert detail_resp.status_code == 200


def test_every_library_document_ships_an_example_pair(client):
    """A ready-made document without an example is a document a first-time
    voter cannot judge: they get two anonymous answers and nothing to compare
    them against. The manifest is small and curated, so this is enforceable.
    """
    for item in client.get("/tool-arena/documents").json():
        assert item["suggested_question"], f"{item['id']} has no suggested question"
        assert item["expected_answer"], f"{item['id']} has no expected answer"


def test_detail_serves_the_same_example_as_the_listing(client):
    """The form prefills from the detail call; the listing is what decides
    whether to advertise an example at all. They must not disagree.
    """
    listed = {d["id"]: d for d in client.get("/tool-arena/documents").json()}
    for doc_id, summary in listed.items():
        detail = client.get(f"/tool-arena/documents/{doc_id}").json()
        assert detail["suggested_question"] == summary["suggested_question"]
        assert detail["expected_answer"] == summary["expected_answer"]
