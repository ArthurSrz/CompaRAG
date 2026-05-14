"""
BUT : déclarer tous les endpoints HTTP du Tool Arena — l'utilisateur démarre
une Comparison, voit deux réponses en aveugle, Vote pour celle qu'il préfère,
puis le BlindReveal lui montre quel RAGTool a produit chaque réponse.

Sera découpé en Phase E selon l'ontologie (cf. knowledge-graph/code-ontology.yaml) :
    backend/tool_arena/comparison/start_comparison_endpoint.py
    backend/tool_arena/comparison/run_comparison_endpoint.py
    backend/tool_arena/vote/cast_vote_endpoint.py
    backend/tool_arena/blind_reveal/reveal_tool_identities_endpoint.py
    backend/tool_arena/leaderboard/show_leaderboard_endpoint.py
    backend/tool_arena/rag_tool/check_tools_are_ready_endpoint.py
    backend/tool_arena/admin/operator_admin_endpoints.py

FastAPI router for the Tool Arena comparison loop.

Provides 4 endpoints:
  POST /tool-arena/session  — create a new session hash
  POST /tool-arena/compare  — dispatch two MCP calls and return blind results
  POST /tool-arena/vote     — record user vote (with guards)
  GET  /tool-arena/reveal   — reveal tool identities after voting

Per D-01: prefix="/tool-arena", tags=["tool-arena"]
Per UX-01: CompareResponse NEVER leaks tool_id, raw_result, server name, or endpoint.
Per D-04: session hash passed via X-Session-Hash header.
Zero imports from backend.arena.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from pathlib import Path

from backend.tool_arena.client import single_mcp_call
from backend.tool_arena.dispatcher import (
    InsufficientReadyServersError,
    MCPDispatcher,
)
from backend.tool_arena.evaluation import EvaluationCatalog
from backend.tool_arena.judge.ground_truth import GroundTruthJudge
from backend.tool_arena.normalizer import normalize_output
from backend.tool_arena.readiness import get_readiness_registry, probe_server
from backend.tool_arena.sanitizer import sanitize_envelope
from backend.tool_arena.document.serve_document_endpoint import documents_router
from utils.storage.redis import REDIS_TOOL_RANKING_KEY, get_redis_client
from backend.tool_arena.models import save_tool_call_to_db, ToolCallRecord
from backend.tool_arena.persistence import ToolVoteRecord, save_tool_vote_to_db
from backend.tool_arena.registry import registry
from backend.tool_arena.session import (
    create_tool_session,
    retrieve_tool_session,
    store_tool_session,
)

logger = logging.getLogger("languia")

router = APIRouter(prefix="/tool-arena", tags=["tool-arena"])
router.include_router(documents_router)

# EvaluationCatalog — backend-side metadata loader for benchmark queries.
# Path resolution: prefer EVAL_QUERIES_PATH env var (Dockerfile copies the
# YAML in), fall back to the in-repo corpus path for local dev. Empty
# catalog when file absent — router validator rejects benchmark requests in
# that case (returns 422, never 500).
_EVAL_QUERIES_PATH = Path(
    os.environ.get(
        "EVAL_QUERIES_PATH",
        str(Path(__file__).resolve().parents[2] / "mcp_servers" / "corpus" / "evaluation" / "queries.yaml"),
    )
)
_eval_catalog = EvaluationCatalog(_EVAL_QUERIES_PATH)
_retrieval_judge = GroundTruthJudge()


# ---------------------------------------------------------------------------
# Admin status router (Phase 2): operator-facing readiness snapshot.
# Mounted under /admin/tool-arena to keep public + admin namespaces separate.
# ---------------------------------------------------------------------------
admin_router = APIRouter(prefix="/admin/tool-arena", tags=["tool-arena-admin"])


def _require_admin_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """Reject requests unless ``Authorization: Bearer <ADMIN_STATUS_TOKEN>``.

    If ``ADMIN_STATUS_TOKEN`` is unset the endpoint is considered "not
    configured" and returns 503 — never 200, never 401 — so misconfigured
    deployments cannot accidentally serve the admin snapshot.
    """
    expected = os.environ.get("ADMIN_STATUS_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=503, detail="Admin status endpoint not configured."
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    token = authorization[len("Bearer "):].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid admin token.")


@admin_router.get("/status")
async def admin_status(_: None = Depends(_require_admin_token)) -> dict:
    """Return the readiness snapshot for all probed servers.

    No PII / secrets — ``last_error`` is already class name + truncated repr.
    """
    snapshot = get_readiness_registry().snapshot()
    return {"servers": [r.to_dict() for r in snapshot]}


# --- Admin OAuth re-key (Phase 3) -------------------------------------------


class OAuthSeedRequest(BaseModel):
    server_id: str
    refresh_token: str
    access_token: str | None = None
    expires_in: int | None = None


@admin_router.post("/oauth/seed")
async def admin_oauth_seed(
    body: OAuthSeedRequest,
    _: None = Depends(_require_admin_token),
) -> dict:
    """Write a freshly-minted refresh_token to storage and re-probe.

    Replaces the deprecated ``{SERVER_ID}_REFRESH_TOKEN`` env-var bootstrap.
    Idempotent: a second seed with the same payload simply overwrites.
    Tokens are NEVER logged.
    """
    from backend.tool_arena import auth as _auth_module
    from backend.tool_arena.credential import _invalidate_cache as _cred_invalidate

    try:
        server = registry.get_server(body.server_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Server '{body.server_id}' not found in registry",
        )

    if server.auth is None or server.auth.type != "oauth2":
        raise HTTPException(
            status_code=400,
            detail=f"Server '{body.server_id}' is not configured for OAuth2",
        )

    await _auth_module.seed_tokens(
        server,
        refresh_token=body.refresh_token,
        access_token=body.access_token,
        expires_in=body.expires_in,
    )
    # OAuth provider is keyed by auth_id (so sibling entries that share an
    # upstream client share storage); invalidate by that key, not by server_id.
    _auth_module._invalidate_cache(server.auth_id)
    _cred_invalidate(body.server_id)
    logger.info("OAuth seed accepted for %s (auth_id=%s)", body.server_id, server.auth_id)

    readiness = await probe_server(server, get_readiness_registry())
    return {
        "server_id": body.server_id,
        "readiness": readiness.to_dict(),
        "seeded_at": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Admin ranking diagnostics


@admin_router.get("/ranking/diag")
async def admin_ranking_diag(_: None = Depends(_require_admin_token)) -> dict:
    """Return the last cron run diagnostics from Redis + latest Postgres entry."""
    from utils.ranking.run import CRON_DIAG_KEY
    from utils.storage.db import db_cursor
    import logging as _log

    _logger = _log.getLogger("languia")
    result: dict = {}

    try:
        client = get_redis_client()
        raw = client.get(CRON_DIAG_KEY)
        result["redis_diag"] = json.loads(raw) if raw else None
    except Exception as e:
        result["redis_diag_error"] = str(e)

    try:
        with db_cursor("get cron diagnostics", _logger) as cursor:
            cursor.execute(
                "SELECT id, ts, payload FROM cron_diagnostics ORDER BY id DESC LIMIT 5"
            )
            rows = cursor.fetchall()
            result["postgres_diag"] = [
                {"id": r[0], "ts": r[1].isoformat() if r[1] else None, "payload": r[2]}
                for r in rows
            ] if rows else []
    except Exception as e:
        result["postgres_diag_error"] = str(e)

    try:
        with db_cursor("get cron sentinel", _logger) as cursor:
            cursor.execute(
                "SELECT id, ts, msg FROM cron_sentinel ORDER BY id DESC LIMIT 5"
            )
            rows = cursor.fetchall()
            result["cron_sentinel"] = [
                {"id": r[0], "ts": r[1].isoformat() if r[1] else None, "msg": r[2]}
                for r in rows
            ] if rows else []
    except Exception as e:
        result["cron_sentinel_error"] = str(e)

    try:
        with db_cursor("get vote counts", _logger) as cursor:
            cursor.execute("""
                SELECT
                    (SELECT COUNT(*) FROM votes WHERE archived = FALSE) as votes_total,
                    (SELECT COUNT(*) FROM reactions WHERE archived = FALSE) as reactions_total,
                    (SELECT COUNT(*) FROM votes v
                     JOIN conversations c ON v.conversation_pair_id = c.conversation_pair_id
                     WHERE v.archived = FALSE AND c.archived = FALSE
                       AND (COALESCE(c.cohorts, '') NOT LIKE '%pix%')) as votes_rankable,
                    (SELECT COUNT(*) FROM reactions r
                     JOIN conversations c ON r.conversation_pair_id = c.conversation_pair_id
                     WHERE r.archived = FALSE AND c.archived = FALSE
                       AND (COALESCE(c.cohorts, '') NOT LIKE '%pix%')) as reactions_rankable
            """)
            row = cursor.fetchone()
            if row:
                result["vote_counts"] = {
                    "votes_total": row[0],
                    "reactions_total": row[1],
                    "votes_rankable": row[2],
                    "reactions_rankable": row[3],
                }
    except Exception as e:
        result["vote_counts_error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CompareRequest(BaseModel):
    # Canonical vocabulary (cf. backend/tool_arena/vocabulary.py) :
    #   task + goal sont les deux moitiés de la `question` du domaine.
    #   La fusion `question` <- (task, goal) sera faite en Phase D
    #   conjointement avec une mise à jour du frontend.
    task: str = Field(default="", description="canonical: question (intent)")
    goal: str = Field(default="", description="canonical: question (success criterion)")
    document_content: str = Field(default="", description="canonical: document")
    # Optional task taxonomy from the UI's "Type de tâche" picker. When set,
    # the dispatcher restricts pairing to entries whose task_type matches —
    # equifinality fairness invariant. Legacy clients (no task_type) get the
    # current behavior: random pick from any group with >=2 READY servers.
    task_type: Literal["summary", "qa", "extraction"] | None = None
    # Phase 13 — haystack mode discriminator. "sandbox" (default) uses
    # document_content as an ephemeral corpus; "benchmark" requires
    # evaluation_query_id to look up the canned task/goal from the catalog.
    haystack: Literal["benchmark", "sandbox"] = "sandbox"
    evaluation_query_id: str | None = None

    @model_validator(mode="after")
    def _validate_haystack_mode(self) -> "CompareRequest":
        if self.haystack == "benchmark":
            if not self.evaluation_query_id:
                raise ValueError(
                    "benchmark mode requires evaluation_query_id"
                )
        else:  # sandbox
            if self.evaluation_query_id:
                raise ValueError(
                    "evaluation_query_id is only valid in benchmark mode"
                )
            if not self.document_content.strip():
                raise ValueError(
                    "sandbox mode requires non-empty document_content"
                )
        return self


class CompareResponse(BaseModel):
    """
    Blind comparison result.
    CRITICAL per UX-01: NO tool_id, NO server name, NO raw_result, NO endpoint.

    Canonical vocabulary (cf. backend/tool_arena/vocabulary.py) :
      session_hash       -> comparison_id (à renommer en Phase E avec migration DB)
      result_a / result_b -> answer_a / answer_b (à renommer en Phase D avec frontend)
    """

    session_hash: str = Field(description="canonical: comparison_id")
    result_a: str | None = Field(description="canonical: answer_a")
    result_b: str | None = Field(description="canonical: answer_b")
    error_a: str | None    # "Tool encountered an error" or None
    error_b: str | None


class ToolPreferencesPayload(BaseModel):
    """Per-side feedback supplied by the user at vote time.

    The pill flags (vote_<pref>_<side>) are kept for back-compat with historical
    rows but are no longer collected from new clients — the UI was replaced by
    a single 1-5 goal-attainment rating per side. Field names mirror tool_votes
    columns so the payload maps 1:1 onto ToolVoteRecord.
    """
    # New: 1-5 goal-attainment rating per side. None when the user submits
    # without rating (e.g. older client).
    vote_goal_rating_a: int | None = Field(default=None, ge=1, le=5)
    vote_goal_rating_b: int | None = Field(default=None, ge=1, le=5)

    # Legacy pill flags. New UIs do not send these; existing rows keep theirs.
    vote_useful_a: bool = False
    vote_useful_b: bool = False
    vote_complete_a: bool = False
    vote_complete_b: bool = False
    vote_creative_a: bool = False
    vote_creative_b: bool = False
    vote_clear_formatting_a: bool = False
    vote_clear_formatting_b: bool = False
    vote_incorrect_a: bool = False
    vote_incorrect_b: bool = False
    vote_superficial_a: bool = False
    vote_superficial_b: bool = False
    vote_instructions_not_followed_a: bool = False
    vote_instructions_not_followed_b: bool = False


class ToolVoteBody(BaseModel):
    chosen: Literal["a", "b", "tie"]
    preferences: ToolPreferencesPayload | None = None


class ToolRevealInfo(BaseModel):
    # Canonical : rag_tool. ToolRevealInfo = identité d'un RAGTool une fois
    # le BlindReveal terminé.
    pos: str              # "a" or "b"
    name: str             # MCPServerConfig.name -> canonical: rag_tool.name
    description: str      # MCPServerConfig.description -> canonical: rag_tool.goal
    duration_ms: int      # from MCPToolCall.duration_ms (0 if error)
    error: str | None     # if tool failed


class ToolRevealResponse(BaseModel):
    chosen: str           # "a" | "b" | "tie"  -> canonical: vote.choice
    tool_a: ToolRevealInfo
    tool_b: ToolRevealInfo


class DryRunRequest(BaseModel):
    tool_id: str


class DryRunCheck(BaseModel):
    name: str             # "connectivity" | "envelope_shape" | "sanitization"
    passed: bool
    detail: str | None = None


class DryRunResponse(BaseModel):
    valid: bool
    tool_id: str
    checks: list[DryRunCheck]
    raw_sample: dict | None = None  # normalized envelope if all checks pass


# ---------------------------------------------------------------------------
# Dependency injection helpers
# ---------------------------------------------------------------------------


def get_tool_session_hash(session_hash: str = Header(..., alias="X-Session-Hash")) -> str:
    if not session_hash:
        raise HTTPException(status_code=400, detail="Missing session hash")
    return session_hash


def get_tool_session(session_hash: str = Depends(get_tool_session_hash)) -> dict:
    try:
        return retrieve_tool_session(session_hash)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Helper: build reveal response from session state
# ---------------------------------------------------------------------------


def _build_reveal_response(session: dict, chosen: str) -> ToolRevealResponse:
    from backend.tool_arena.registry import registry

    tool_a = session["tool_a"]
    tool_b = session["tool_b"]
    server_a = registry.get_server(tool_a["tool_id"])
    server_b = registry.get_server(tool_b["tool_id"])
    return ToolRevealResponse(
        chosen=chosen,
        tool_a=ToolRevealInfo(
            pos="a",
            name=server_a.name,
            description=server_a.description,
            duration_ms=tool_a.get("duration_ms", 0),
            error=tool_a.get("error"),
        ),
        tool_b=ToolRevealInfo(
            pos="b",
            name=server_b.name,
            description=server_b.description,
            duration_ms=tool_b.get("duration_ms", 0),
            error=tool_b.get("error"),
        ),
    )


# ---------------------------------------------------------------------------
# Endpoint 0: GET /tool-arena/leaderboard
# ---------------------------------------------------------------------------


@router.get("/leaderboard")
async def get_tool_leaderboard():
    """
    Return current tool rankings from Redis.

    Response shape: {data_timestamp: float|null, tools: [{tool_id, elo, ..., prefs: {...}|null}, ...]}
    Each tool entry merges the ranking row with its preferences block (or null
    if no prefs aggregated yet — mirrors LLM /models endpoint shape).
    Returns empty tools list if Redis is unavailable or no data exists yet.
    """
    try:
        client = get_redis_client()
        raw = client.get(REDIS_TOOL_RANKING_KEY)
    except Exception:
        return {"data_timestamp": None, "tools": []}
    if not raw:
        return {"data_timestamp": None, "tools": []}
    data = json.loads(raw)
    rankings = data.get("rankings", {})
    preferences = data.get("preferences", {})
    tools = [
        {**entry, "prefs": preferences.get(tool_id)}
        for tool_id, entry in rankings.items()
    ]
    return {
        "data_timestamp": data.get("timestamp"),
        "tools": tools,
    }


# ---------------------------------------------------------------------------
# Endpoint 0b: POST /tool-arena/dry-run
# ---------------------------------------------------------------------------

_DRY_RUN_TASK = "What is this document about?"
_DRY_RUN_GOAL = "Provide a brief summary"
_DRY_RUN_TIMEOUT = 30  # seconds


@router.post("/dry-run", response_model=DryRunResponse)
async def dry_run(body: DryRunRequest) -> DryRunResponse:
    """Validate a registered RAG tool end-to-end with a hardcoded test prompt.

    Runs three checks:
      1. connectivity — real MCP call with 30s timeout
      2. envelope_shape — normalize_output produces non-empty answer
      3. sanitization — sanitize_envelope runs without error (best-effort)

    Returns structured pass/fail with detail for each check.
    """
    # Lookup — 404 if not registered
    try:
        server = registry.get_server(body.tool_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Tool '{body.tool_id}' not found in registry")

    checks: list[DryRunCheck] = []
    raw_text: str | None = None
    duration_ms: int = 0

    # --- Check 1: connectivity ---
    try:
        raw_text, duration_ms = await asyncio.wait_for(
            single_mcp_call(server, _DRY_RUN_TASK, _DRY_RUN_GOAL),
            timeout=_DRY_RUN_TIMEOUT,
        )
        checks.append(DryRunCheck(name="connectivity", passed=True, detail=f"MCP call succeeded in {duration_ms}ms"))
    except asyncio.TimeoutError:
        checks.append(DryRunCheck(name="connectivity", passed=False, detail=f"MCP call timed out after {_DRY_RUN_TIMEOUT}s"))
    except Exception as exc:
        checks.append(DryRunCheck(name="connectivity", passed=False, detail=str(exc)))

    if not checks[0].passed:
        # Skip remaining checks — no output to validate
        checks.append(DryRunCheck(name="envelope_shape", passed=False, detail="Skipped — connectivity failed"))
        checks.append(DryRunCheck(name="sanitization", passed=False, detail="Skipped — connectivity failed"))
        return DryRunResponse(valid=False, tool_id=body.tool_id, checks=checks, raw_sample=None)

    # --- Check 2: envelope_shape ---
    envelope = None
    try:
        envelope = normalize_output(raw_text, duration_ms)
        if not envelope.answer or not envelope.answer.strip():
            checks.append(DryRunCheck(name="envelope_shape", passed=False, detail="Normalized answer is empty"))
            envelope = None
        else:
            checks.append(DryRunCheck(name="envelope_shape", passed=True, detail=f"Answer: {len(envelope.answer)} chars, sources: {len(envelope.sources)}"))
    except Exception as exc:
        checks.append(DryRunCheck(name="envelope_shape", passed=False, detail=f"normalize_output raised: {exc}"))
        envelope = None

    if envelope is None:
        checks.append(DryRunCheck(name="sanitization", passed=False, detail="Skipped — envelope_shape failed"))
        return DryRunResponse(valid=False, tool_id=body.tool_id, checks=checks, raw_sample=None)

    # --- Check 3: sanitization (best-effort, always passes) ---
    try:
        sanitized = sanitize_envelope(envelope, [server])
        stripped_urls = sum(1 for s in sanitized.sources if s.url is None)
        checks.append(DryRunCheck(name="sanitization", passed=True, detail=f"Sanitized {stripped_urls} source URLs"))
        final_envelope = sanitized
    except Exception as exc:
        # Sanitization is best-effort — log but still pass
        logger.warning("dry_run sanitization raised (non-fatal): %s", exc)
        checks.append(DryRunCheck(name="sanitization", passed=True, detail=f"Sanitization skipped (non-fatal): {exc}"))
        final_envelope = envelope

    valid = all(c.passed for c in checks)
    return DryRunResponse(
        valid=valid,
        tool_id=body.tool_id,
        checks=checks,
        raw_sample=final_envelope.model_dump() if valid else None,
    )


# ---------------------------------------------------------------------------
# Endpoint 1: POST /tool-arena/session
# ---------------------------------------------------------------------------


@router.post("/session")
async def create_session():
    """Create a new tool arena session hash (UUID)."""
    session_hash = create_tool_session()
    return {"session_hash": session_hash}


# ---------------------------------------------------------------------------
# Endpoint 2: POST /tool-arena/compare
# ---------------------------------------------------------------------------


@router.post("/compare")
async def compare(body: CompareRequest, request: Request):
    """
    Dispatch two MCP calls concurrently and return blind, sanitized results.

    Per UX-01: response contains ONLY mediated_result (as result_a/result_b).
    tool_id, raw_result, server name, and endpoint are NEVER exposed.

    Content negotiation (Wave 6.8):
      - Accept: text/event-stream → multiplexed SSE stream of per-side
        progress events terminating in {type:'complete'}.
      - default / application/json → CompareResponse (sync path).
    """
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        from backend.tool_arena.streaming import (
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

        # Create the session up-front so the SSE consumer can wire
        # X-Session-Hash for vote/reveal. on_complete persists tool_a /
        # tool_b dicts matching the sync path's payload shape, so the
        # downstream /vote and /reveal endpoints work unchanged.
        stream_session_hash = create_tool_session()

        def _persist(results: dict, errors: dict) -> None:
            tool_a_id = server_a.id
            tool_b_id = server_b.id
            llm_a = server_a.llm_id or ""
            llm_b = server_b.llm_id or ""

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
                "llm_id_a": llm_a,
                "llm_id_b": llm_b,
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

    session_hash = create_tool_session()

    # Benchmark mode: look up the canned query in the catalog and substitute
    # its task/goal text into the dispatcher call. The body's task/goal are
    # ignored here (they default to "" in benchmark mode — slice 4.4 enforces
    # evaluation_query_id presence; slice 4.7 looks up the actual text).
    effective_task = body.task
    effective_goal = body.goal
    if body.haystack == "benchmark":
        assert body.evaluation_query_id is not None  # validated by model_validator
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
        # Surface as 503 with a structured body so the frontend can pattern-
        # match on `error: "tool_unavailable"` and show a single
        # "temporarily unavailable" message instead of two error cards.
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
    # payload so the vote endpoint can persist them onto tool_votes.judgement_*
    # at vote time (Wave 5 / slice 5.10 + 5.11).
    if body.haystack == "benchmark":
        assert body.evaluation_query_id is not None
        eval_meta = _eval_catalog.get(body.evaluation_query_id)
        expected = list(eval_meta.expected_spans) if eval_meta else []
        for tc in (tool_a, tool_b):
            spans = getattr(tc, "retrieved_spans", None) or []
            tc.judgement = _retrieval_judge.score(spans, expected).to_dict()

    # Persist both tool calls to DB early (don't lose data if user never votes)
    for tc in (tool_a, tool_b):
        try:
            record = ToolCallRecord(**tc.model_dump(mode="json"))
            save_tool_call_to_db(record.model_dump(mode="json"))
        except Exception as exc:
            logger.error("Failed to persist tool_call %s: %s", tc.call_id, exc)

    # Store full state in Redis (tool_id included — never sent to client).
    # Each server now uses its own LLM (set in mcp_servers.json); the session
    # tracks both for the vote record.
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

    # Build blind response — per D-13: error becomes generic message
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


# ---------------------------------------------------------------------------
# Endpoint 3: POST /tool-arena/vote
# ---------------------------------------------------------------------------


@router.post("/vote", response_model=ToolRevealResponse)
async def vote(
    body: ToolVoteBody,
    session_hash: str = Depends(get_tool_session_hash),
    session: dict = Depends(get_tool_session),
):
    """
    Record user's blind vote and reveal tool identities.

    Guards:
      - 403 if already voted (re-vote prevention, Pitfall 2)
      - 422 if either tool failed (voting not meaningful, Pitfall 6)
    """
    # Guard: re-vote prevention (Pitfall 2)
    if session.get("voted"):
        raise HTTPException(status_code=403, detail="Already voted")

    # Guard: at least one tool failed — comparison is not meaningful
    # (Pitfall 6, extended). If either side errored, the user shouldn't be
    # asked to vote between a working tool and a broken one. The frontend
    # hides the vote area on either-failed; this is the server-side mirror
    # so an old client or a direct API call can't bypass the gate.
    if session["tool_a"].get("error") or session["tool_b"].get("error"):
        raise HTTPException(status_code=422, detail="At least one tool failed, vote not possible")

    # Mark session as voted
    session["voted"] = True
    session["chosen"] = body.chosen
    store_tool_session(session_hash, session)

    # Persist vote to DB. tool_votes.llm_id keeps a single string for back-compat:
    # store tool_a's llm_id (typically equal to tool_b's when both are RAG servers
    # we control). For per-tool granularity, query tool_calls.llm_id instead.
    tool_a = session["tool_a"]
    tool_b = session["tool_b"]
    prefs_dump = body.preferences.model_dump() if body.preferences else {}
    vote_record = ToolVoteRecord(
        session_hash=session_hash,
        tool_a_id=tool_a["tool_id"],
        tool_b_id=tool_b["tool_id"],
        chosen=body.chosen,
        llm_id=session.get("llm_id_a") or session.get("llm_id_b") or "",
        task=session["task"],
        goal=session["goal"],
        timestamp=datetime.now().isoformat(),
        **prefs_dump,
    )
    try:
        save_tool_vote_to_db(vote_record.model_dump(mode="json"))
    except Exception as exc:
        logger.error("Failed to persist tool_vote for session %s: %s", session_hash, exc)

    return _build_reveal_response(session, body.chosen)


# ---------------------------------------------------------------------------
# Endpoint 4: GET /tool-arena/reveal
# ---------------------------------------------------------------------------


@router.get("/reveal", response_model=ToolRevealResponse)
async def reveal(session: dict = Depends(get_tool_session)):
    """
    Return tool identities and vote outcome.

    Guard: 403 if user has not voted yet (Pitfall 3).
    """
    if not session.get("voted"):
        raise HTTPException(status_code=403, detail="Vote required before reveal")

    return _build_reveal_response(session, session["chosen"])
