"""InterviewProtocol is backend-enforced: force_artifact must reach the tool
at the turn cap, past the deadline, and on finish-early — never decided by
the tool itself (ontology invariant).
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from backend.tool_arena.interview.contracts import (
    InterviewFinishRequest,
    InterviewReplyRequest,
)
from backend.tool_arena.interview.interview_protocol import should_force_artifact
from backend.tool_arena.tests.interview_testkit import (
    INTERVIEW_MODULE,
    FakeSessionStore,
    artifact_move,
)
from backend.tool_arena.tests.test_interview_reply_loop import (
    make_session,
    registry_patch,
)

pytestmark = pytest.mark.anyio


def test_should_force_artifact_at_cap_and_deadline():
    assert should_force_artifact(10, 10, deadline_ts=9e12) is True
    assert should_force_artifact(11, 10, deadline_ts=9e12) is True
    assert should_force_artifact(9, 10, deadline_ts=9e12) is False
    assert should_force_artifact(1, 10, deadline_ts=time.time() - 5) is True


async def test_reply_at_turn_cap_forces_artifact():
    from backend.tool_arena.interview.run_interview_endpoints import reply

    session = make_session(max_turns=2)
    arm = session["interview"]["arms"]["a"]
    arm["transcript"] += [
        {"role": "expert", "content": "a1"},
        {"role": "interviewer", "content": "Q2"},
    ]
    arm["turn"] = 1

    store = FakeSessionStore()
    move = AsyncMock(return_value=(artifact_move("# Artifact"), 50))
    with (
        registry_patch(),
        patch(f"{INTERVIEW_MODULE}.store_tool_session", store.store),
        patch(f"{INTERVIEW_MODULE}.retrieve_tool_session", store.retrieve),
        patch(f"{INTERVIEW_MODULE}.single_interview_move", move),
    ):
        response = await reply(
            InterviewReplyRequest(arm="a", answer="a2 — final answer"),
            session_hash="h1",
            session=session,
        )

    assert move.await_args.kwargs["force_artifact"] is True
    assert response.state.done is True
    assert response.state.type == "artifact"
    assert store.sessions["h1"]["interview"]["arms"]["a"]["artifact"] == "# Artifact"


async def test_reply_past_deadline_forces_artifact():
    from backend.tool_arena.interview.run_interview_endpoints import reply

    session = make_session(max_turns=10, deadline_ts=time.time() - 10)
    store = FakeSessionStore()
    move = AsyncMock(return_value=(artifact_move("# A"), 50))
    with (
        registry_patch(),
        patch(f"{INTERVIEW_MODULE}.store_tool_session", store.store),
        patch(f"{INTERVIEW_MODULE}.retrieve_tool_session", store.retrieve),
        patch(f"{INTERVIEW_MODULE}.single_interview_move", move),
    ):
        await reply(
            InterviewReplyRequest(arm="a", answer="first answer"),
            session_hash="h1",
            session=session,
        )

    assert move.await_args.kwargs["force_artifact"] is True


async def test_concurrent_finishes_both_commit():
    """Regression (prod 2026-08-14): Terminer A + Terminer B clicked together —
    each request read the session before the other wrote, last-writer-wins
    clobbered one arm's done and both_done never became true. The commit
    phase must re-read fresh state so both arms survive."""
    from backend.tool_arena.interview.run_interview_endpoints import finish_arm

    session = make_session()
    store = FakeSessionStore()
    store.store("h1", session)
    move = AsyncMock(return_value=(artifact_move("# Done"), 50))
    with (
        registry_patch(),
        patch(f"{INTERVIEW_MODULE}.store_tool_session", store.store),
        patch(f"{INTERVIEW_MODULE}.retrieve_tool_session", store.retrieve),
        patch(f"{INTERVIEW_MODULE}.single_interview_move", move),
    ):
        import asyncio as aio
        import copy
        r_a, r_b = await aio.gather(
            finish_arm(InterviewFinishRequest(arm="a"), session_hash="h1",
                       session=copy.deepcopy(session)),
            finish_arm(InterviewFinishRequest(arm="b"), session_hash="h1",
                       session=copy.deepcopy(session)),
        )

    stored = store.sessions["h1"]["interview"]["arms"]
    assert stored["a"]["done"] and stored["b"]["done"]
    assert stored["a"]["artifact"] == "# Done" and stored["b"]["artifact"] == "# Done"
    # At least the later commit must see both arms done.
    assert r_a.both_done or r_b.both_done


async def test_finish_early_forces_artifact_without_new_answer():
    from backend.tool_arena.interview.run_interview_endpoints import finish_arm

    session = make_session()
    store = FakeSessionStore()
    move = AsyncMock(return_value=(artifact_move("# Early"), 50))
    with (
        registry_patch(),
        patch(f"{INTERVIEW_MODULE}.store_tool_session", store.store),
        patch(f"{INTERVIEW_MODULE}.retrieve_tool_session", store.retrieve),
        patch(f"{INTERVIEW_MODULE}.single_interview_move", move),
    ):
        response = await finish_arm(
            InterviewFinishRequest(arm="b"),
            session_hash="h1",
            session=session,
        )

    assert move.await_args.kwargs["force_artifact"] is True
    assert response.state.done is True
    # No expert message was appended — finish-early sends no answer.
    transcript = store.sessions["h1"]["interview"]["arms"]["b"]["transcript"]
    assert all(e["role"] == "interviewer" for e in transcript)
