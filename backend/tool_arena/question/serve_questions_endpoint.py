"""
BUT : exposer au frontend la liste des Questions à vérité de référence
connue, pour qu'il puisse proposer le mode benchmark au lieu de l'avoir
en dur sur « bac à sable ».

Questions sub-router — the benchmark catalogue (GET /questions).

Mirrors documents_router: unauthenticated, cacheable, metadata only.

The response carries id, query_text and goal_text, and deliberately NOT
expected_spans. Ground truth never crosses to the browser: a client that
knows which passages are expected could be used to grade — or to game —
the very duel it is voting on. The judge runs server-side (see
judge_verdict/) and the catalogue loader already separates the two
(list_questions_with_known_answers keeps spans for the backend's own use).

An empty catalogue is a normal state, not an error: the corpus may not be
mounted yet. The frontend hides the benchmark option rather than offering
a mode that would 422.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel

from backend.tool_arena.question.list_questions_with_known_answers import (
    evaluation_catalog,
)

questions_router = APIRouter()

# Same policy as the document catalogue — the ground-truth set changes on
# deploy, not per request.
_QUESTIONS_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"


class QuestionSummary(BaseModel):
    """What the picker needs, and nothing a voter could grade themselves with."""

    id: str
    query_text: str
    goal_text: str


@questions_router.get("/questions")
async def list_questions(response: Response) -> list[QuestionSummary]:
    response.headers["Cache-Control"] = _QUESTIONS_CACHE_CONTROL
    return [
        QuestionSummary(
            id=meta.id, query_text=meta.query_text, goal_text=meta.goal_text
        )
        for meta in (
            evaluation_catalog.get(query_id) for query_id in evaluation_catalog.list_ids()
        )
        if meta is not None
    ]
