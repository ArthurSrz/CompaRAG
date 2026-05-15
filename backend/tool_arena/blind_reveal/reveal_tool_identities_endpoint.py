"""
BUT : montrer à l'utilisateur l'identité des deux RAGTool qu'il vient de
comparer, APRÈS qu'il ait voté. Sans vote préalable, on refuse (403) —
l'aveuglement de la Comparison ne doit jamais être levé prématurément.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.tool_arena.blind_reveal.identify_user_session import (
    build_reveal_response,
    get_tool_session,
)
from backend.tool_arena.comparison.contracts import ToolRevealResponse

reveal_router = APIRouter()


@reveal_router.get("/reveal", response_model=ToolRevealResponse)
async def reveal(session: dict = Depends(get_tool_session)):
    """Return tool identities and vote outcome.

    Guard: 403 if the user has not voted yet (Pitfall 3).
    """
    if not session.get("voted"):
        raise HTTPException(status_code=403, detail="Vote required before reveal")

    return build_reveal_response(session, session["chosen"])
