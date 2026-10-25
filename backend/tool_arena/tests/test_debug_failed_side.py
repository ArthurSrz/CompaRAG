"""Operator debug — naming the tool behind a side that failed.

A duel where one tool errors offers no vote, and the reveal screen requires
one, so the failing tool could never be identified from the interface: the
user could only retry. The response now names it, and nothing wider — a side
that answered stays anonymous, because that one is still being judged.

Minimal-app pattern from test_router_compare_benchmark.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tool_arena.router import router

_app = FastAPI()
_app.include_router(router)
client = TestClient(_app)

_BODY = {
    "task": "Quelle est la référence du palier arrière ?",
    "goal": "Réponse exacte.",
    "document_content": "Le palier arrière porte la référence PAL-3300-B.",
    "task_type": "qa",
}


def _fake_tool_call(tool_id: str, error: str | None = None):
    tc = MagicMock()
    tc.call_id = f"call-{tool_id}"
    tc.tool_id = tool_id
    tc.error = error
    tc.mediated_result = f"answer-from-{tool_id}"
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
        "error": error,
    }
    return tc


def _post(body: dict, tool_a, tool_b):
    fake_disp_instance = MagicMock()
    fake_disp_instance.dispatch = AsyncMock(return_value=(tool_a, tool_b))
    with (
        patch(
            "backend.tool_arena.comparison.run_comparison_endpoint.MCPDispatcher",
            return_value=fake_disp_instance,
        ),
        patch("backend.tool_arena.comparison.run_comparison_endpoint.save_tool_call_to_db"),
        patch(
            "backend.tool_arena.comparison.run_comparison_endpoint.create_tool_session",
            return_value="sess-x",
        ),
        patch("backend.tool_arena.comparison.run_comparison_endpoint.store_tool_session"),
    ):
        return client.post("/tool-arena/compare", json=body)


def test_the_failed_side_is_named_with_its_real_exception():
    resp = _post(
        _BODY,
        _fake_tool_call("srv-a"),
        _fake_tool_call("srv-b", error="ValueError: No embedding data received"),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["debug_b"] == {
        "tool_id": "srv-b",
        "error": "ValueError: No embedding data received",
    }
    # The side that answered is still being judged, so it stays anonymous.
    assert body["debug_a"] is None
    # The user-facing message is untouched — debug adds, it does not replace.
    assert body["error_b"] == "Tool encountered an error"


def test_a_duel_where_both_answered_names_neither():
    resp = _post(
        _BODY,
        _fake_tool_call("srv-a"),
        _fake_tool_call("srv-b"),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["debug_a"] is None
    assert body["debug_b"] is None
