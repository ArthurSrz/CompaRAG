"""
BUT : démarrer une Comparison vide — réserver un comparison_id (UUID) que
le frontend utilisera ensuite pour faire pointer vote et reveal sur la bonne
manche. Endpoint purement d'initialisation, ne lance pas encore les RAGTool.
"""
from __future__ import annotations

from fastapi import APIRouter

from backend.tool_arena.blind_reveal.remember_who_was_which import create_tool_session

start_comparison_router = APIRouter()


@start_comparison_router.post("/session")
async def create_session():
    """Create a new tool arena session hash (UUID)."""
    session_hash = create_tool_session()
    return {"session_hash": session_hash}
