"""Tests for the /tool-arena/vote either-failed guard.

The pre-vote display shows a "Tool encountered an error" card whenever a
side fails. Asking the user to vote between a working tool and an errored
one isn't a meaningful comparison, so the vote endpoint rejects with 422
when *either* side errored. The frontend mirrors this with `eitherFailed`
hiding the vote area; this guard catches old clients and direct API calls.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tool_arena.router import router, get_tool_session, get_tool_session_hash


def _client_with_session(session_payload: dict) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tool_session_hash] = lambda: "test-hash"
    app.dependency_overrides[get_tool_session] = lambda: session_payload
    return TestClient(app)


def _ok_call(tool_id: str = "tool-x") -> dict:
    return {
        "tool_id": tool_id,
        "llm_id": "llm-x",
        "raw_result": "answer",
        "mediated_result": "answer",
        "duration_ms": 100,
        "error": None,
    }


def _err_call(tool_id: str = "tool-y") -> dict:
    return {
        "tool_id": tool_id,
        "llm_id": "llm-y",
        "raw_result": "",
        "mediated_result": "",
        "duration_ms": 0,
        "error": "MCPToolError: Engine 'X' failed: No embedding data received",
    }


def test_vote_rejected_when_only_tool_a_failed():
    session = {
        "voted": False,
        "tool_a": _err_call("tool-a"),
        "tool_b": _ok_call("tool-b"),
    }
    client = _client_with_session(session)
    resp = client.post(
        "/tool-arena/vote",
        json={"chosen": "b", "preferences": None},
        headers={"X-Session-Hash": "test-hash"},
    )
    assert resp.status_code == 422
    assert "at least one tool failed" in resp.json()["detail"].lower()


def test_vote_rejected_when_only_tool_b_failed():
    session = {
        "voted": False,
        "tool_a": _ok_call("tool-a"),
        "tool_b": _err_call("tool-b"),
    }
    client = _client_with_session(session)
    resp = client.post(
        "/tool-arena/vote",
        json={"chosen": "a", "preferences": None},
        headers={"X-Session-Hash": "test-hash"},
    )
    assert resp.status_code == 422


def test_vote_rejected_when_both_failed():
    session = {
        "voted": False,
        "tool_a": _err_call("tool-a"),
        "tool_b": _err_call("tool-b"),
    }
    client = _client_with_session(session)
    resp = client.post(
        "/tool-arena/vote",
        json={"chosen": "tie", "preferences": None},
        headers={"X-Session-Hash": "test-hash"},
    )
    assert resp.status_code == 422
