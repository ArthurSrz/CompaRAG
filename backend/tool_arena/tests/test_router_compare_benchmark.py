"""Router substitution — benchmark mode reads task/goal from EvaluationCatalog.

Slice 4.7: when haystack='benchmark', the route handler must look up
evaluation_query_id in the catalog and pass its query_text/goal_text to the
dispatcher (the user's body has them empty in benchmark mode — they live in
the catalog, not the API call).

Uses the minimal-app pattern from test_dry_run.py:14-20 to avoid psycopg2 /
Redis blocking imports.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tool_arena.dispatcher import MCPDispatcher
from backend.tool_arena.question.list_questions_with_known_answers import EvaluationCatalog, EvaluationQueryMeta
from backend.tool_arena.router import router

_app = FastAPI()
_app.include_router(router)
client = TestClient(_app)


def _fake_tool_call(tool_id: str):
    """Build a MagicMock whose model_dump() returns a dict that survives
    Pydantic validation by ToolCallRecord. Only the fields used by the route
    matter for this test (task/goal substitution); the rest are filler."""
    tc = MagicMock()
    tc.call_id = f"call-{tool_id}"
    tc.tool_id = tool_id
    tc.mediated_result = f"answer-from-{tool_id}"
    tc.error = None
    tc.model_dump.return_value = {
        "call_id": tc.call_id,
        "session_id": "sess-x",
        "task": "stub-task",
        "goal": "stub-goal",
        "tool_id": tool_id,
        "llm_id": "stub-llm",
        "raw_result": "stub-raw",
        "mediated_result": tc.mediated_result,
        "duration_ms": 100,
        "created_at": "2026-05-11T00:00:00Z",
        "error": None,
    }
    return tc


def test_benchmark_mode_substitutes_task_and_goal_from_eval_query() -> None:
    """Slice 4.7 — POST /tool-arena/compare with haystack=benchmark +
    evaluation_query_id sends the catalog's query_text/goal_text to the
    dispatcher, NOT the (empty) values in the request body."""
    fake_catalog = EvaluationCatalog.__new__(EvaluationCatalog)
    fake_catalog._path = "fake.yaml"  # not read; we override the cached map
    fake_catalog.__dict__["_by_id"] = {
        "q01_capital_france": EvaluationQueryMeta(
            id="q01_capital_france",
            query_text="Quelle est la capitale de la France ?",
            goal_text="Réponse précise.",
        )
    }
    dispatch_mock = AsyncMock(
        return_value=(_fake_tool_call("srv-a"), _fake_tool_call("srv-b"))
    )
    fake_disp_instance = MagicMock()
    fake_disp_instance.dispatch = dispatch_mock

    with (
        patch("backend.tool_arena.router.MCPDispatcher", return_value=fake_disp_instance),
        patch("backend.tool_arena.router._eval_catalog", fake_catalog, create=True),
        patch("backend.tool_arena.router.save_tool_call_to_db"),
        patch("backend.tool_arena.router.create_tool_session", return_value="sess-x"),
        patch("backend.tool_arena.router.store_tool_session"),
    ):
        response = client.post(
            "/tool-arena/compare",
            json={
                "haystack": "benchmark",
                "evaluation_query_id": "q01_capital_france",
            },
        )

    assert response.status_code == 200, response.text
    assert dispatch_mock.await_count == 1
    kwargs = dispatch_mock.await_args.kwargs
    # Dispatcher received the catalog's task/goal, not the body's (empty) values
    assert kwargs["task"] == "Quelle est la capitale de la France ?"
    assert kwargs["goal"] == "Réponse précise."
    # document_content stays empty — rag_pill server resolves FixedCorpus
    assert kwargs["document_content"] == ""


def test_benchmark_mode_unknown_evaluation_query_id_returns_422() -> None:
    """Unknown evaluation_query_id can't be substituted — route returns 422
    rather than passing empty task/goal through (which dispatcher would
    accept silently)."""
    fake_catalog = EvaluationCatalog.__new__(EvaluationCatalog)
    fake_catalog._path = "fake.yaml"
    fake_catalog.__dict__["_by_id"] = {}  # empty catalog

    fake_disp_instance = MagicMock()
    fake_disp_instance.dispatch = AsyncMock(return_value=())  # not reached
    with (
        patch("backend.tool_arena.router.MCPDispatcher", return_value=fake_disp_instance),
        patch("backend.tool_arena.router._eval_catalog", fake_catalog, create=True),
        patch("backend.tool_arena.router.save_tool_call_to_db"),
        patch("backend.tool_arena.router.create_tool_session", return_value="sess-x"),
        patch("backend.tool_arena.router.store_tool_session"),
    ):
        response = client.post(
            "/tool-arena/compare",
            json={
                "haystack": "benchmark",
                "evaluation_query_id": "missing_query",
            },
        )

    assert response.status_code == 422
    assert "missing_query" in response.text or "evaluation_query_id" in response.text
