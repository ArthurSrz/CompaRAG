"""POST /tool-arena/interview/reply — transcript growth, turn accounting,
tolerant parsing of the tool's move payload.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.tool_arena.interview.contracts import InterviewReplyRequest
from backend.tool_arena.rag_tool.ask_one_interview_move import parse_move
from backend.tool_arena.rag_tool.ask_one_tool import MCPToolError
from backend.tool_arena.tests.interview_testkit import (
    INTERVIEW_MODULE,
    FakeSessionStore,
    interview_server,
    question_move,
    wire_registry,
)

pytestmark = pytest.mark.anyio


def make_session(max_turns: int = 10, deadline_ts: float = 9e12) -> dict:
    return {
        "session_hash": "h1",
        "task": "t",
        "goal": "g",
        "task_type": "knowledge_capture",
        "voted": False,
        "llm_id_a": "llm",
        "llm_id_b": "llm",
        "tool_a": {"tool_id": "interview_grill", "llm_id": "llm", "error": "wip", "duration_ms": 0},
        "tool_b": {"tool_id": "interview_gsd", "llm_id": "llm", "error": "wip", "duration_ms": 0},
        "interview": {
            "max_turns": max_turns,
            "deadline_ts": deadline_ts,
            "server_a_id": "interview_grill",
            "server_b_id": "interview_gsd",
            "finalized": False,
            "arms": {
                "a": {"transcript": [{"role": "interviewer", "content": "Q1"}],
                       "turn": 0, "done": False, "artifact": None,
                       "artifact_subtype": None, "error": None, "duration_ms_total": 0},
                "b": {"transcript": [{"role": "interviewer", "content": "Q1b"}],
                       "turn": 0, "done": False, "artifact": None,
                       "artifact_subtype": None, "error": None, "duration_ms_total": 0},
            },
        },
    }


def registry_patch():
    grill = interview_server("interview_grill", "grill")
    gsd = interview_server("interview_gsd", "gsd_discuss")
    return patch(f"{INTERVIEW_MODULE}.registry", wire_registry(grill, gsd))


async def test_reply_appends_answer_and_next_question():
    from backend.tool_arena.interview.run_interview_endpoints import reply

    session = make_session()
    store = FakeSessionStore()
    move = AsyncMock(return_value=(question_move("Q2"), 30))
    with (
        registry_patch(),
        patch(f"{INTERVIEW_MODULE}.store_tool_session", store.store),
        patch(f"{INTERVIEW_MODULE}.retrieve_tool_session", store.retrieve),
        patch(f"{INTERVIEW_MODULE}.single_interview_move", move),
    ):
        response = await reply(
            InterviewReplyRequest(arm="a", answer="my answer"),
            session_hash="h1",
            session=session,
        )

    assert response.state.type == "question"
    assert response.state.question == "Q2"
    assert response.state.turn == 1
    assert response.both_done is False
    transcript = store.sessions["h1"]["interview"]["arms"]["a"]["transcript"]
    assert [e["role"] for e in transcript] == ["interviewer", "expert", "interviewer"]
    assert transcript[1]["content"] == "my answer"
    # turn passed to the tool = expert answers so far + 1
    assert move.await_args.kwargs["turn"] == 2


async def test_reply_on_done_arm_is_409():
    from fastapi import HTTPException

    from backend.tool_arena.interview.run_interview_endpoints import reply

    session = make_session()
    session["interview"]["arms"]["a"]["done"] = True
    with registry_patch():
        with pytest.raises(HTTPException) as exc:
            await reply(
                InterviewReplyRequest(arm="a", answer="late answer"),
                session_hash="h1",
                session=session,
            )
    assert exc.value.status_code == 409


async def test_reply_after_vote_is_403():
    from fastapi import HTTPException

    from backend.tool_arena.interview.run_interview_endpoints import reply

    session = make_session()
    session["voted"] = True
    with registry_patch():
        with pytest.raises(HTTPException) as exc:
            await reply(
                InterviewReplyRequest(arm="a", answer="answer"),
                session_hash="h1",
                session=session,
            )
    assert exc.value.status_code == 403


async def test_tool_failure_marks_arm_error_not_500():
    from backend.tool_arena.interview.run_interview_endpoints import reply

    session = make_session()
    store = FakeSessionStore()
    with (
        registry_patch(),
        patch(f"{INTERVIEW_MODULE}.store_tool_session", store.store),
        patch(f"{INTERVIEW_MODULE}.retrieve_tool_session", store.retrieve),
        patch(
            f"{INTERVIEW_MODULE}.single_interview_move",
            new_callable=AsyncMock,
            side_effect=MCPToolError("boom"),
        ),
    ):
        response = await reply(
            InterviewReplyRequest(arm="a", answer="answer"),
            session_hash="h1",
            session=session,
        )

    assert response.state.type == "error"
    assert response.state.done is True
    # Generic message only — internals never reach the client.
    assert "boom" not in (response.state.error or "")


# ── parse_move: tolerant parsing unit tests ─────────────────────────────────

def test_parse_move_valid_question():
    move = parse_move('{"type": "question", "question": "Q?"}', force_artifact=False)
    assert move == {"type": "question", "question": "Q?"}


def test_parse_move_valid_artifact():
    move = parse_move(
        '{"type": "artifact", "artifact_markdown": "# K", "metadata": {"artifact_subtype": "mental_model"}}',
        force_artifact=False,
    )
    assert move["type"] == "artifact"
    assert move["artifact_markdown"] == "# K"
    assert move["artifact_subtype"] == "mental_model"


def test_parse_move_garbage_becomes_question():
    move = parse_move("Just plain text, not JSON", force_artifact=False)
    assert move == {"type": "question", "question": "Just plain text, not JSON"}


def test_parse_move_garbage_under_force_becomes_artifact():
    move = parse_move("# My knowledge dump", force_artifact=True)
    assert move["type"] == "artifact"
    assert move["artifact_markdown"] == "# My knowledge dump"


def test_parse_move_error_payload_raises():
    with pytest.raises(MCPToolError):
        parse_move('{"type": "error", "error": "unknown strategy"}', force_artifact=False)


def test_parse_move_question_under_force_becomes_artifact():
    """Regression (prod 2026-08-14): on finish-early the tool re-emitted its
    previous question; under force_artifact the arm must close regardless."""
    move = parse_move(
        '{"type": "question", "question": "Q4 again?"}', force_artifact=True
    )
    assert move["type"] == "artifact"
    assert move["artifact_markdown"] == "Q4 again?"
