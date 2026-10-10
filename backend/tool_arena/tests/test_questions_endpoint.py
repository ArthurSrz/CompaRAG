"""GET /tool-arena/questions — the benchmark catalogue.

The real questions_router is mounted directly: unlike the compare endpoint,
it imports nothing that blocks on network (no Redis, no psycopg2, no MCP
dispatcher), which is the point of having moved the catalogue singleton
into the question package.

The assertion that matters most is that ground truth does NOT ship to the
browser. A client holding expected_spans could grade — or game — the duel
it is about to vote on.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tool_arena.question.list_questions_with_known_answers import (
    EvaluationCatalog,
    evaluation_catalog,
)
from backend.tool_arena.question.serve_questions_endpoint import questions_router

_app = FastAPI()
_app.include_router(questions_router, prefix="/tool-arena")
client = TestClient(_app)


def test_lists_the_catalogue() -> None:
    resp = client.get("/tool-arena/questions")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == len(evaluation_catalog.list_ids())
    assert {q["id"] for q in body} == set(evaluation_catalog.list_ids())


def test_every_entry_carries_what_the_picker_needs() -> None:
    for entry in client.get("/tool-arena/questions").json():
        assert entry["query_text"].strip(), f"{entry['id']} has no question text"
        assert "goal_text" in entry


def test_ground_truth_never_reaches_the_client() -> None:
    """Expected spans stay server-side. The judge runs there; a browser that
    knew the answer could grade itself."""
    for entry in client.get("/tool-arena/questions").json():
        assert "expected_spans" not in entry
        assert "char_start" not in str(entry)


def test_response_is_cacheable() -> None:
    """The catalogue changes on deploy, not per request — same policy as the
    document listing."""
    resp = client.get("/tool-arena/questions")
    assert "max-age" in resp.headers.get("Cache-Control", "")


def test_a_missing_catalogue_is_an_empty_list_not_an_error(tmp_path, monkeypatch) -> None:
    """The corpus may not be mounted yet. The frontend then hides the
    benchmark option rather than offering a mode that would 422."""
    empty = EvaluationCatalog(tmp_path / "absent.yaml")
    monkeypatch.setattr(
        "backend.tool_arena.question.serve_questions_endpoint.evaluation_catalog",
        empty,
    )
    resp = client.get("/tool-arena/questions")
    assert resp.status_code == 200
    assert resp.json() == []
