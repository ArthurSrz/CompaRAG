"""
BUT : agréger sous /tool-arena tous les sous-routeurs déclarés par les
endpoints répartis selon l'ontologie. Ce fichier ne contient plus de logique
métier — il monte juste les routes des autres modules.

Endpoints (par entité — cf. knowledge-graph/code-ontology.yaml) :
    POST /tool-arena/session     -> comparison/start_comparison_endpoint.py
    POST /tool-arena/compare     -> comparison/run_comparison_endpoint.py
    POST /tool-arena/vote        -> vote/cast_vote_endpoint.py
    GET  /tool-arena/reveal      -> blind_reveal/reveal_tool_identities_endpoint.py
    GET  /tool-arena/leaderboard -> leaderboard/show_leaderboard_endpoint.py
    POST /tool-arena/dry-run     -> rag_tool/check_tools_are_ready_endpoint.py
    /tool-arena/documents/...    -> document/serve_document_endpoint.py

Routes admin (séparées sous /admin/tool-arena) :
    -> admin/operator_admin_endpoints.py

Per D-01: prefix="/tool-arena", tags=["tool-arena"]
Per UX-01: CompareResponse NEVER leaks tool_id, raw_result, server name, or endpoint.
Per D-04: session hash passed via X-Session-Hash header.
"""
from __future__ import annotations

from fastapi import APIRouter

from backend.tool_arena.admin.operator_admin_endpoints import admin_router
from backend.tool_arena.blind_reveal.reveal_tool_identities_endpoint import reveal_router
from backend.tool_arena.comparison.run_comparison_endpoint import run_comparison_router
from backend.tool_arena.comparison.start_comparison_endpoint import (
    start_comparison_router,
)
from backend.tool_arena.document.serve_document_endpoint import documents_router
from backend.tool_arena.leaderboard.show_leaderboard_endpoint import leaderboard_router
from backend.tool_arena.rag_tool.check_tools_are_ready_endpoint import dry_run_router
from backend.tool_arena.vote.cast_vote_endpoint import vote_router

# Public-facing arena routes.
router = APIRouter(prefix="/tool-arena", tags=["tool-arena"])
router.include_router(documents_router)
router.include_router(leaderboard_router)
router.include_router(dry_run_router)
router.include_router(start_comparison_router)
router.include_router(run_comparison_router)
router.include_router(vote_router)
router.include_router(reveal_router)

# admin_router has its own prefix (/admin/tool-arena) declared at the source.
__all__ = ["router", "admin_router"]
