"""POST /tool-arena/interview/start — pairing, readiness gate, opening moves.

The dispatcher's fairness invariant must hold: knowledge_capture tools only
pair with each other, and the readiness gate returns 503 when fewer than two
are READY. Opening questions must be sanitized before they enter the
transcript (BlindProtocol).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.tool_arena.interview.contracts import InterviewStartRequest
from backend.tool_arena.rag_tool.readiness import (
    _reset_registry_for_tests,
    get_readiness_registry,
)
from backend.tool_arena.tests.interview_testkit import (
    DISPATCHER_MODULE,
    INTERVIEW_MODULE,
    FakeSessionStore,
    interview_server,
    question_move,
    rag_server,
    wire_registry,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _reset():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


async def test_start_pairs_only_knowledge_capture_servers():
    from backend.tool_arena.interview.run_interview_endpoints import start_interview

    grill = interview_server("interview_grill", "grill")
    gsd = interview_server("interview_gsd", "gsd_discuss")
    qa = rag_server("qa_tool")
    mock_registry = wire_registry(grill, gsd, qa)
    reg = get_readiness_registry()
    for s in (grill, gsd, qa):
        reg.set_ready(s.id)

    store = FakeSessionStore()
    with (
        patch(f"{DISPATCHER_MODULE}.registry", mock_registry),
        patch(f"{INTERVIEW_MODULE}.registry", mock_registry),
        patch(f"{INTERVIEW_MODULE}.store_tool_session", store.store),
        patch(f"{INTERVIEW_MODULE}.retrieve_tool_session", store.retrieve),
        patch(
            f"{INTERVIEW_MODULE}.single_interview_move",
            new_callable=AsyncMock,
            return_value=(question_move("What is your domain?"), 42),
        ),
    ):
        response = await start_interview(InterviewStartRequest(task="t", goal="g"))

    session = store.sessions[response.session_hash]
    paired = {session["interview"]["server_a_id"], session["interview"]["server_b_id"]}
    assert paired == {"interview_grill", "interview_gsd"}
    assert response.arm_a.type == "question"
    assert response.arm_b.type == "question"
    assert response.arm_a.question == "What is your domain?"


async def test_start_returns_503_when_one_capture_server_ready():
    from backend.tool_arena.interview.run_interview_endpoints import start_interview

    grill = interview_server("interview_grill", "grill")
    qa_a, qa_b = rag_server("qa_a"), rag_server("qa_b")
    mock_registry = wire_registry(grill, qa_a, qa_b)
    reg = get_readiness_registry()
    for s in (grill, qa_a, qa_b):
        reg.set_ready(s.id)

    with (
        patch(f"{DISPATCHER_MODULE}.registry", mock_registry),
        patch(f"{INTERVIEW_MODULE}.registry", mock_registry),
    ):
        response = await start_interview(InterviewStartRequest(task="t", goal="g"))

    assert response.status_code == 503


async def test_start_sanitizes_opening_questions():
    from backend.tool_arena.interview.run_interview_endpoints import start_interview

    grill = interview_server("interview_grill", "grill")
    gsd = interview_server("interview_gsd", "gsd_discuss")
    mock_registry = wire_registry(grill, gsd)
    reg = get_readiness_registry()
    for s in (grill, gsd):
        reg.set_ready(s.id)

    store = FakeSessionStore()
    with (
        patch(f"{DISPATCHER_MODULE}.registry", mock_registry),
        patch(f"{INTERVIEW_MODULE}.registry", mock_registry),
        patch(f"{INTERVIEW_MODULE}.store_tool_session", store.store),
        patch(f"{INTERVIEW_MODULE}.retrieve_tool_session", store.retrieve),
        patch(
            f"{INTERVIEW_MODULE}.sanitize_output",
            side_effect=lambda text, servers: text.replace("grilling", "[redacted]"),
        ),
        patch(
            f"{INTERVIEW_MODULE}.single_interview_move",
            new_callable=AsyncMock,
            return_value=(question_move("A grilling question"), 10),
        ),
    ):
        response = await start_interview(InterviewStartRequest(task="t", goal="g"))

    assert response.arm_a.question == "A [redacted] question"


async def test_start_stores_vote_blocking_placeholders():
    """Before finalize, tool_a/tool_b must carry an error so an early /vote
    hits its existing 422 guard instead of crashing."""
    from backend.tool_arena.interview.run_interview_endpoints import start_interview

    grill = interview_server("interview_grill", "grill")
    gsd = interview_server("interview_gsd", "gsd_discuss")
    mock_registry = wire_registry(grill, gsd)
    reg = get_readiness_registry()
    for s in (grill, gsd):
        reg.set_ready(s.id)

    store = FakeSessionStore()
    with (
        patch(f"{DISPATCHER_MODULE}.registry", mock_registry),
        patch(f"{INTERVIEW_MODULE}.registry", mock_registry),
        patch(f"{INTERVIEW_MODULE}.store_tool_session", store.store),
        patch(f"{INTERVIEW_MODULE}.retrieve_tool_session", store.retrieve),
        patch(
            f"{INTERVIEW_MODULE}.single_interview_move",
            new_callable=AsyncMock,
            return_value=(question_move("Q1"), 10),
        ),
    ):
        response = await start_interview(InterviewStartRequest(task="t", goal="g"))

    session = store.sessions[response.session_hash]
    assert session["tool_a"]["error"]
    assert session["tool_b"]["error"]
    assert session["voted"] is False
