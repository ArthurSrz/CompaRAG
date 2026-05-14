"""
BUT : sauvegarder un Vote en base de données après que l'utilisateur a choisi
entre les deux réponses anonymes. Sert ensuite à alimenter le Leaderboard et
le DatasetExport.

Future home (cf. knowledge-graph/code-ontology.yaml) :
    backend/tool_arena/vote/save_vote_to_database.py

Database persistence for tool arena votes.

Stores blind comparison votes in the tool_votes table.
Isolated from backend.arena — uses the local db() context manager from models.py.
"""

from pydantic import BaseModel

from backend.tool_arena.models import db  # reuse local db() context manager


class ToolVoteRecord(BaseModel):
    """
    DB serialization model for a tool arena vote.

    All fields are flat primitive types ready for parameterized INSERT.
    Matches the tool_votes table columns exactly (per D-19/D-20).
    """

    session_hash: str
    tool_a_id: str
    tool_b_id: str
    chosen: str          # "a" | "b" | "tie"
    llm_id: str
    task: str
    goal: str
    timestamp: str       # ISO format
    competitor_type: str = "tool"

    # 1-5 goal-attainment rating per side. NULL for legacy rows that pre-date
    # the star UI; required nullability matches the SMALLINT column.
    vote_goal_rating_a: int | None = None
    vote_goal_rating_b: int | None = None

    # Per-side preference flags (mirror LLM `votes` table). Default False so
    # callers that don't supply prefs continue to work unchanged.
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

    # Phase 13 — benchmark/sandbox discriminator + per-side retrieval-quality
    # judgement payload (JSONB). Defaulted so legacy callers that don't
    # supply these fields continue to work; sandbox votes leave the
    # judgement_* columns NULL (the judge only runs in benchmark mode).
    haystack_mode: str = "sandbox"
    evaluation_query_id: str | None = None
    judgement_a: dict | None = None
    judgement_b: dict | None = None


def save_tool_vote_to_db(data: dict) -> dict:
    """
    Save a tool arena vote to the tool_votes table.

    Args:
        data: ToolVoteRecord.model_dump(mode='json') with all flat fields

    Returns:
        dict: The saved data dict

    Raises:
        psycopg2.Error: If database operation fails
    """
    with db(data, "save 'tool_vote'") as (cursor, fields, values):
        cursor.execute(
            f"INSERT INTO tool_votes ({fields}) VALUES ({values})",
            data,
        )
    return data
