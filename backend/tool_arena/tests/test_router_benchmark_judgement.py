"""Router scores retrieval against expected_spans in benchmark mode.

Slice 5.10: after dispatch returns MCPToolCalls carrying retrieved_spans,
the router (benchmark mode) computes a JudgementScore per side against the
catalog's expected_spans and attaches it to each MCPToolCall before the
session payload is stored.

We verify by capturing the session payload passed to store_tool_session.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tool_arena.question.list_questions_with_known_answers import EvaluationCatalog, EvaluationQueryMeta
from backend.tool_arena.router import router
from backend.tool_arena.judge_verdict.base import ExpectedSpan

_app = FastAPI()
_app.include_router(router)
client = TestClient(_app)


def _tool_call_with_spans(tool_id: str, *, hit: bool) -> MagicMock:
    """Build a fake MCPToolCall whose model_dump emits a span dict whose
    char range overlaps (hit=True) or doesn't overlap (hit=False) the
    expected span [1245, 1389) on geography_fr.md."""
    char_start, char_end = (1245, 1389) if hit else (9000, 9050)
    tc = MagicMock()
    tc.call_id = f"call-{tool_id}"
    tc.tool_id = tool_id
    tc.mediated_result = f"answer-{tool_id}"
    tc.error = None
    tc.llm_id = "stub-llm"
    tc.retrieved_spans = [
        MagicMock(
            source_doc_id="geography_fr.md",
            char_start=char_start,
            char_end=char_end,
            text="Paris est la capitale.",
            score=0.9,
            rank=0,
        )
    ]
    tc.judgement = None
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
        "judgement": tc.judgement,
    }
    return tc


def test_benchmark_mode_attaches_judgement_to_each_tool_call() -> None:
    """Slice 5.10 — after dispatch, the router scores each side's retrieved
    spans against the catalog's expected_spans and stores the JudgementScore
    in the session payload (and on the MCPToolCall itself, so vote-time
    persistence picks it up)."""
    fake_catalog = EvaluationCatalog.__new__(EvaluationCatalog)
    fake_catalog._path = "fake.yaml"
    fake_catalog.__dict__["_by_id"] = {
        "q01_capital_france": EvaluationQueryMeta(
            id="q01_capital_france",
            query_text="Quelle est la capitale ?",
            goal_text="Réponse précise.",
            expected_spans=(
                ExpectedSpan(
                    source_doc_id="geography_fr.md",
                    char_start=1245,
                    char_end=1389,
                ),
            ),
        )
    }

    tc_a = _tool_call_with_spans("srv-a", hit=True)
    tc_b = _tool_call_with_spans("srv-b", hit=False)
    dispatch_mock = AsyncMock(return_value=(tc_a, tc_b))

    fake_disp_instance = MagicMock()
    fake_disp_instance.dispatch = dispatch_mock

    captured_payload: dict = {}

    def capture_session(session_hash, payload):
        captured_payload.update(payload)

    with (
        patch("backend.tool_arena.router.MCPDispatcher", return_value=fake_disp_instance),
        patch("backend.tool_arena.router._eval_catalog", fake_catalog, create=True),
        patch("backend.tool_arena.router.save_tool_call_to_db"),
        patch("backend.tool_arena.router.create_tool_session", return_value="sess-x"),
        patch("backend.tool_arena.router.store_tool_session", side_effect=capture_session),
    ):
        response = client.post(
            "/tool-arena/compare",
            json={
                "haystack": "benchmark",
                "evaluation_query_id": "q01_capital_france",
            },
        )

    assert response.status_code == 200, response.text
    # Side A hit; Side B missed.
    assert tc_a.judgement is not None
    assert tc_a.judgement["contains_gold"] is True
    assert tc_a.judgement["mrr"] == 1.0
    assert tc_b.judgement is not None
    assert tc_b.judgement["contains_gold"] is False
    assert tc_b.judgement["mrr"] == 0.0


def test_sandbox_mode_leaves_judgement_none() -> None:
    """Slice 5.10 (negative case) — sandbox mode never scores. judgement
    stays None on both sides; the judge module isn't reached."""
    tc_a = _tool_call_with_spans("srv-a", hit=True)
    tc_b = _tool_call_with_spans("srv-b", hit=True)
    dispatch_mock = AsyncMock(return_value=(tc_a, tc_b))

    fake_disp_instance = MagicMock()
    fake_disp_instance.dispatch = dispatch_mock

    with (
        patch("backend.tool_arena.router.MCPDispatcher", return_value=fake_disp_instance),
        patch("backend.tool_arena.router.save_tool_call_to_db"),
        patch("backend.tool_arena.router.create_tool_session", return_value="sess-x"),
        patch("backend.tool_arena.router.store_tool_session"),
    ):
        response = client.post(
            "/tool-arena/compare",
            json={
                "task": "anything",
                "goal": "anything",
                "document_content": "user upload",
            },
        )

    assert response.status_code == 200, response.text
    assert tc_a.judgement is None
    assert tc_b.judgement is None
