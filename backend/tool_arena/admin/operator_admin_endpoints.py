"""
BUT : endpoints réservés aux opérateurs du Tool Arena (pas aux utilisateurs
finaux) — voir l'état des RAGTool, réinjecter un refresh_token OAuth quand
un fournisseur externe rote ses clés, consulter le diagnostic du ranking
nocturne. Protégés par un bearer token (ADMIN_STATUS_TOKEN).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException

from backend.tool_arena.comparison.contracts import OAuthSeedRequest
from backend.tool_arena.rag_tool.list_available_tools import registry
from backend.tool_arena.rag_tool.readiness import get_readiness_registry, probe_server
from utils.storage.redis import get_redis_client

logger = logging.getLogger("languia")

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
