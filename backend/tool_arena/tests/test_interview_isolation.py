"""Arm isolation — the core ontology invariant: the Interview is a VARIANT
generated independently by each tool. Nothing the expert tells arm A may ever
appear in a call to arm B's tool.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.tool_arena.interview.contracts import InterviewReplyRequest
from backend.tool_arena.tests.interview_testkit import (
    INTERVIEW_MODULE,
    FakeSessionStore,
    question_move,
)
from backend.tool_arena.tests.test_interview_reply_loop import (
    make_session,
    registry_patch,
)

pytestmark = pytest.mark.anyio


async def test_arm_b_call_never_contains_arm_a_content():
    from backend.tool_arena.interview.run_interview_endpoints import reply

    session = make_session()
    store = FakeSessionStore()
    move = AsyncMock(return_value=(question_move("next?"), 10))

    secrets = [
        "SECRET-A-1 the real trick is preheating",
        "SECRET-A-2 never trust the gauge",
        "SECRET-A-3 always check twice",
    ]

    with (
        registry_patch(),
        patch(f"{INTERVIEW_MODULE}.store_tool_session", store.store),
        patch(f"{INTERVIEW_MODULE}.single_interview_move", move),
    ):
        for secret in secrets:
            session = store.sessions.get("h1", session)
            await reply(
                InterviewReplyRequest(arm="a", answer=secret),
                session_hash="h1",
                session=session,
            )
        session = store.sessions["h1"]
        await reply(
            InterviewReplyRequest(arm="b", answer="unrelated b answer"),
            session_hash="h1",
            session=session,
        )

    b_call = move.await_args_list[-1]
    assert b_call.kwargs["server"].id == "interview_gsd"
    b_transcript_text = str(b_call.kwargs["transcript"])
    for secret in secrets:
        assert "SECRET-A" not in b_transcript_text or secret not in b_transcript_text
    assert "SECRET-A" not in b_transcript_text

    # And symmetrically: arm a's calls never saw arm b's answer.
    for call in move.await_args_list[:-1]:
        assert "unrelated b answer" not in str(call.kwargs["transcript"])
