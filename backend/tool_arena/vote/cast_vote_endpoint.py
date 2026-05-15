"""
BUT : recueillir le Vote de l'utilisateur entre les deux réponses anonymes,
le persister en base, et révéler l'identité des deux RAGTool dans le même
appel HTTP (le vote déclenche le reveal — invariant produit pour empêcher
qu'un utilisateur découvre les identités avant d'avoir choisi).

Garde-fous :
    - 403 si l'utilisateur a déjà voté pour cette Comparison
    - 422 si l'un des deux RAGTool est en erreur (le vote n'a pas de sens)
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from backend.tool_arena.blind_reveal.identify_user_session import (
    build_reveal_response,
    get_tool_session,
    get_tool_session_hash,
)
from backend.tool_arena.blind_reveal.remember_who_was_which import store_tool_session
from backend.tool_arena.comparison.contracts import ToolRevealResponse, ToolVoteBody
from backend.tool_arena.vote.save_vote_to_database import (
    ToolVoteRecord,
    save_tool_vote_to_db,
)

logger = logging.getLogger("languia")

vote_router = APIRouter()


@vote_router.post("/vote", response_model=ToolRevealResponse)
async def vote(
    body: ToolVoteBody,
    session_hash: str = Depends(get_tool_session_hash),
    session: dict = Depends(get_tool_session),
):
    """Record the user's blind vote and reveal tool identities in one shot."""
    # Guard: re-vote prevention (Pitfall 2)
    if session.get("voted"):
        raise HTTPException(status_code=403, detail="Already voted")

    # Guard: at least one tool failed — comparison is not meaningful.
    # The frontend hides the vote area on either-failed; this is the server-side
    # mirror so an old client or a direct API call can't bypass the gate.
    if session["tool_a"].get("error") or session["tool_b"].get("error"):
        raise HTTPException(status_code=422, detail="At least one tool failed, vote not possible")

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

    return build_reveal_response(session, body.chosen)
