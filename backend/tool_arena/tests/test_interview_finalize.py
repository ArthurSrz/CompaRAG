"""POST /tool-arena/interview/finalize — artifacts flow into the standard
normalize -> sanitize -> MCPToolCall -> persist pipeline, and the resulting
session is accepted by the EXISTING /vote endpoint unchanged.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tool_arena.tests.interview_testkit import (
    INTERVIEW_MODULE,
    FakeSessionStore,
    interview_server,
    wire_registry,
)
from backend.tool_arena.tests.test_interview_reply_loop import make_session

pytestmark = pytest.mark.anyio


def finished_session() -> dict:
    session = make_session()
    for key, artifact in (("a", "# Artifact A"), ("b", "# Artifact B")):
        arm = session["interview"]["arms"][key]
        arm["transcript"] += [
            {"role": "expert", "content": f"answer {key}"},
            {"role": "interviewer", "content": f"followup {key}"},
        ]
        arm["turn"] = 1
        arm["done"] = True
        arm["artifact"] = artifact
        arm["artifact_subtype"] = "mental_model"
        arm["duration_ms_total"] = 1200
    return session


def interview_patches(store: FakeSessionStore, save_mock: MagicMock):
    grill = interview_server("interview_grill", "grill")
    gsd = interview_server("interview_gsd", "gsd_discuss")
    return (
        patch(f"{INTERVIEW_MODULE}.registry", wire_registry(grill, gsd)),
        patch(f"{INTERVIEW_MODULE}.store_tool_session", store.store),
        patch(f"{INTERVIEW_MODULE}.retrieve_tool_session", store.retrieve),
        patch(f"{INTERVIEW_MODULE}.save_tool_call_to_db", save_mock),
    )


async def test_finalize_requires_both_arms_done():
    from fastapi import HTTPException

    from backend.tool_arena.interview.run_interview_endpoints import finalize

    session = finished_session()
    session["interview"]["arms"]["b"]["done"] = False
    store, save = FakeSessionStore(), MagicMock()
    p1, p2, p3, p4 = interview_patches(store, save)
    with p1, p2, p3, p4:
        with pytest.raises(HTTPException) as exc:
            await finalize(session_hash="h1", session=session)
    assert exc.value.status_code == 409
    save.assert_not_called()


async def test_finalize_builds_vote_compatible_session_and_persists():
    from backend.tool_arena.interview.run_interview_endpoints import finalize

    session = finished_session()
    store, save = FakeSessionStore(), MagicMock()
    p1, p2, p3, p4 = interview_patches(store, save)
    with p1, p2, p3, p4:
        response = await finalize(session_hash="h1", session=session)

    assert response.result_a == "# Artifact A"
    assert response.result_b == "# Artifact B"
    assert response.error_a is None and response.error_b is None

    stored = store.sessions["h1"]
    assert stored["tool_a"]["tool_id"] == "interview_grill"
    assert stored["tool_b"]["tool_id"] == "interview_gsd"
    assert stored["tool_a"]["error"] is None
    assert stored["interview"]["finalized"] is True

    # Persisted: transcript markdown as raw_result, artifact as mediated_result.
    assert save.call_count == 2
    rows = [call.args[0] for call in save.call_args_list]
    row_a = next(r for r in rows if r["tool_id"] == "interview_grill")
    assert "**Q:**" in row_a["raw_result"] and "**A:**" in row_a["raw_result"]
    assert row_a["mediated_result"] == "# Artifact A"
    assert row_a["session_id"] == "h1"


async def test_finalize_is_idempotent():
    from backend.tool_arena.interview.run_interview_endpoints import finalize

    session = finished_session()
    store, save = FakeSessionStore(), MagicMock()
    p1, p2, p3, p4 = interview_patches(store, save)
    with p1, p2, p3, p4:
        first = await finalize(session_hash="h1", session=session)
        second = await finalize(session_hash="h1", session=store.sessions["h1"])

    assert save.call_count == 2  # not re-persisted on the second call
    assert first.result_a == second.result_a
    assert first.result_b == second.result_b


async def test_failed_arm_surfaces_generic_error():
    from backend.tool_arena.interview.run_interview_endpoints import finalize

    session = finished_session()
    arm_b = session["interview"]["arms"]["b"]
    arm_b["artifact"] = None
    arm_b["error"] = "TimeoutError: too slow"
    store, save = FakeSessionStore(), MagicMock()
    p1, p2, p3, p4 = interview_patches(store, save)
    with p1, p2, p3, p4:
        response = await finalize(session_hash="h1", session=session)

    assert response.result_a == "# Artifact A"
    assert response.result_b is None
    assert response.error_b == "Tool encountered an error"
    assert "TimeoutError" not in (response.error_b or "")


async def test_existing_vote_endpoint_accepts_finalized_session():
    """The finalized session must pass /vote's guards untouched — the whole
    point of finalize is to hand over to the existing vote/reveal path."""
    from backend.tool_arena.comparison.contracts import ToolVoteBody
    from backend.tool_arena.interview.run_interview_endpoints import finalize
    from backend.tool_arena.vote import cast_vote_endpoint

    session = finished_session()
    store, save = FakeSessionStore(), MagicMock()
    p1, p2, p3, p4 = interview_patches(store, save)
    with p1, p2, p3, p4:
        await finalize(session_hash="h1", session=session)

    finalized = store.sessions["h1"]
    reveal = MagicMock()
    with (
        patch.object(cast_vote_endpoint, "store_tool_session", store.store),
        patch.object(cast_vote_endpoint, "save_tool_vote_to_db", MagicMock()),
        patch.object(cast_vote_endpoint, "build_reveal_response", reveal),
    ):
        await cast_vote_endpoint.vote(
            ToolVoteBody(chosen="a"),
            session_hash="h1",
            session=finalized,
        )

    assert store.sessions["h1"]["voted"] is True
    reveal.assert_called_once()
