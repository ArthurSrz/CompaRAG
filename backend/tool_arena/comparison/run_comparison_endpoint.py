"""
BUT : LE point central du Tool Arena — recevoir une Question, choisir deux
RAGTool prêts, leur poser la question en parallèle, et renvoyer leurs deux
Answer en aveugle (sans révéler quel outil a produit laquelle).

Deux modes de réponse selon l'en-tête Accept :
  - text/event-stream : flux SSE multiplexé (progression des deux outils
    en direct) — le navigateur affiche deux ProgressCard animées.
  - application/json (défaut) : réponse synchrone CompareResponse.

Deux modes de Question :
  - sandbox  : la question vient du body, le Document est uploadé
  - benchmark : la question est tirée du catalogue (Question avec vérité
    de référence connue) et un JudgeVerdict scorera chaque Answer.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.tool_arena.blind_reveal.remember_who_was_which import (
    create_tool_session,
    store_tool_session,
)
from backend.tool_arena.comparison.ask_two_tools_concurrently import (
    InsufficientReadyServersError,
    MCPDispatcher,
)
from backend.tool_arena.comparison.contracts import CompareRequest, CompareResponse
from backend.tool_arena.judge_verdict.score_against_ground_truth import GroundTruthJudge
from backend.tool_arena.models import ToolCallRecord, save_tool_call_to_db
from backend.tool_arena.question.list_questions_with_known_answers import (
    EvaluationCatalog,
)

logger = logging.getLogger("languia")

run_comparison_router = APIRouter()

# EvaluationCatalog — backend-side metadata loader for benchmark queries.
# Path resolution: prefer EVAL_QUERIES_PATH env var (Dockerfile copies the
# YAML in), fall back to the in-repo corpus path for local dev. Empty
# catalog when file absent — the validator rejects benchmark requests in
# that case (returns 422, never 500).
_EVAL_QUERIES_PATH = Path(
    os.environ.get(
        "EVAL_QUERIES_PATH",
        str(
            Path(__file__).resolve().parents[3]
            / "mcp_servers"
            / "corpus"
            / "evaluation"
            / "queries.yaml"
        ),
    )
)
_eval_catalog = EvaluationCatalog(_EVAL_QUERIES_PATH)
_retrieval_judge = GroundTruthJudge()


@run_comparison_router.post("/compare")
async def compare(body: CompareRequest, request: Request):
    """
    Dispatch two MCP calls concurrently and return blind, sanitized results.

    Per UX-01: response contains ONLY mediated_result (as result_a/result_b).
    tool_id, raw_result, server name, and endpoint are NEVER exposed.
    """
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        return await _compare_streaming(body)
    return await _compare_sync(body)


async def _compare_streaming(body: CompareRequest):
    """SSE path: stream per-side progress events, terminate with `complete`."""
    from backend.tool_arena.comparison.stream_progress_to_browser import (
        create_sse_response,
        stream_compare,
    )

    dispatcher = MCPDispatcher()
    try:
        server_a, server_b = await dispatcher.pick_pair(task_type=body.task_type)
    except InsufficientReadyServersError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "error": "tool_unavailable",
                "message": (
                    "Not enough MCP tools are currently available to run a "
                    "comparison. Please try again shortly."
                ),
                "ready_count": exc.ready_count,
            },
        )

    effective_task = body.task
    effective_goal = body.goal
    if body.haystack == "benchmark":
        assert body.evaluation_query_id is not None
        eval_meta = _eval_catalog.get(body.evaluation_query_id)
        if eval_meta is None:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "unknown_evaluation_query_id",
                    "evaluation_query_id": body.evaluation_query_id,
                },
            )
        effective_task = eval_meta.query_text
        effective_goal = eval_meta.goal_text

    # Create the session up-front so the SSE consumer can wire X-Session-Hash
    # for vote/reveal. on_complete persists tool_a / tool_b dicts matching the
    # sync path's payload shape, so /vote and /reveal work unchanged.
    stream_session_hash = create_tool_session()

    def _persist(results: dict, errors: dict) -> None:
        def _payload(server, result: dict | None, error: str | None) -> dict:
            if error is not None or result is None:
                return {
                    "tool_id": server.id,
                    "llm_id": server.llm_id or "",
                    "mediated_result": "",
                    "error": error or "Tool encountered an error",
                    "duration_ms": 0,
                }
            return {
                "tool_id": server.id,
                "llm_id": server.llm_id or "",
                "mediated_result": result.get("answer") or "",
                "error": None,
                "duration_ms": int(
                    (result.get("retrieval_latency_ms") or 0)
                    + (result.get("generation_latency_ms") or 0)
                ),
                "retrieved_spans": result.get("retrieved_spans", []),
            }

        payload = {
            "session_hash": stream_session_hash,
            "task": effective_task,
            "goal": effective_goal,
            "llm_id_a": server_a.llm_id or "",
            "llm_id_b": server_b.llm_id or "",
            "voted": False,
            "tool_a": _payload(server_a, results.get("a"), errors.get("a")),
            "tool_b": _payload(server_b, results.get("b"), errors.get("b")),
        }
        store_tool_session(stream_session_hash, payload)

    return create_sse_response(
        stream_compare(
            server_a,
            server_b,
            task=effective_task,
            goal=effective_goal,
            document_content=body.document_content,
            session_hash=stream_session_hash,
            on_complete=_persist,
        )
    )


async def _compare_sync(body: CompareRequest):
    """Synchronous path: return CompareResponse with blind result_a/result_b."""
    from backend.tool_arena.vote.save_vote_to_database import (  # noqa: F401 (kept for parity)
        ToolVoteRecord,
    )

    session_hash = create_tool_session()

    # Benchmark mode: substitute the catalog's task/goal text. The body's
    # task/goal default to "" in benchmark mode (model_validator).
    effective_task = body.task
    effective_goal = body.goal
    if body.haystack == "benchmark":
        assert body.evaluation_query_id is not None
        eval_meta = _eval_catalog.get(body.evaluation_query_id)
        if eval_meta is None:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "unknown_evaluation_query_id",
                    "message": (
                        f"evaluation_query_id={body.evaluation_query_id!r} not "
                        f"found in catalog."
                    ),
                    "evaluation_query_id": body.evaluation_query_id,
                },
            )
        effective_task = eval_meta.query_text
        effective_goal = eval_meta.goal_text

    dispatcher = MCPDispatcher()
    try:
        tool_a, tool_b = await dispatcher.dispatch(
            task=effective_task,
            goal=effective_goal,
            session_id=session_hash,
            document_content=body.document_content,
            task_type=body.task_type,
        )
    except InsufficientReadyServersError as exc:
        logger.warning(
            "tool-arena/compare: returning 503 tool_unavailable (ready_count=%d)",
            exc.ready_count,
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": "tool_unavailable",
                "message": (
                    "Not enough MCP tools are currently available to run a "
                    "comparison. Please try again shortly."
                ),
                "ready_count": exc.ready_count,
            },
        )

    # Benchmark mode: score each side's retrieved spans against the catalog's
    # expected spans. Scores ride on MCPToolCall.judgement and the session
    # payload so /vote can persist them onto tool_votes.judgement_* at vote time.
    if body.haystack == "benchmark":
        assert body.evaluation_query_id is not None
        eval_meta = _eval_catalog.get(body.evaluation_query_id)
        expected = list(eval_meta.expected_spans) if eval_meta else []
        for tc in (tool_a, tool_b):
            spans = getattr(tc, "retrieved_spans", None) or []
            tc.judgement = _retrieval_judge.score(spans, expected).to_dict()

    # Persist both tool calls to DB early (don't lose data if user never votes).
    for tc in (tool_a, tool_b):
        try:
            record = ToolCallRecord(**tc.model_dump(mode="json"))
            save_tool_call_to_db(record.model_dump(mode="json"))
        except Exception as exc:
            logger.error("Failed to persist tool_call %s: %s", tc.call_id, exc)

    # Store full state in Redis (tool_id included — never sent to client).
    session_payload = {
        "session_hash": session_hash,
        "task": body.task,
        "goal": body.goal,
        "llm_id_a": tool_a.llm_id,
        "llm_id_b": tool_b.llm_id,
        "voted": False,
        "tool_a": tool_a.model_dump(mode="json"),
        "tool_b": tool_b.model_dump(mode="json"),
    }
    store_tool_session(session_hash, session_payload)

    # Build blind response — per D-13: error becomes generic message.
    result_a = tool_a.mediated_result if tool_a.error is None else None
    result_b = tool_b.mediated_result if tool_b.error is None else None
    error_a = "Tool encountered an error" if tool_a.error is not None else None
    error_b = "Tool encountered an error" if tool_b.error is not None else None

    return CompareResponse(
        session_hash=session_hash,
        result_a=result_a,
        result_b=result_b,
        error_a=error_a,
        error_b=error_b,
    )
