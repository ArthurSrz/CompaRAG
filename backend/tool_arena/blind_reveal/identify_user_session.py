"""
BUT : reconnaître quelle Comparison appartient à l'utilisateur qui frappe à
la porte de /vote ou /reveal. Le navigateur envoie un en-tête X-Session-Hash
qu'on traduit en l'état stocké en Redis pour cette comparison.

Inclut aussi le helper `build_reveal_response` qui construit le payload de
révélation à partir d'un état de session (utilisé par /vote ET /reveal).
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from backend.tool_arena.blind_reveal.remember_who_was_which import retrieve_tool_session
from backend.tool_arena.comparison.contracts import ToolRevealInfo, ToolRevealResponse


def get_tool_session_hash(session_hash: str = Header(..., alias="X-Session-Hash")) -> str:
    if not session_hash:
        raise HTTPException(status_code=400, detail="Missing session hash")
    return session_hash


def get_tool_session(session_hash: str = Depends(get_tool_session_hash)) -> dict:
    try:
        return retrieve_tool_session(session_hash)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def build_reveal_response(session: dict, chosen: str) -> ToolRevealResponse:
    """Reveal the two RAGTool identities once the user has voted."""
    from backend.tool_arena.rag_tool.list_available_tools import registry

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
