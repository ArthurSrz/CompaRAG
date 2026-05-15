"""
BUT : décrire les contrats échangés via HTTP pendant une Comparison —
ce que l'utilisateur envoie (CompareRequest, ToolVoteBody) et ce que le
backend renvoie (CompareResponse, ToolRevealResponse, DryRunResponse).

Pas de logique métier, juste des Pydantic models. Sortis de router.py en
Phase E pour que la responsabilité "déclarer les endpoints" et "déclarer
leurs contrats" vivent dans des fichiers séparés.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CompareRequest(BaseModel):
    # Canonical vocabulary (cf. backend/tool_arena/vocabulary.py) :
    #   task + goal sont les deux moitiés de la `question` du domaine.
    #   La fusion `question` <- (task, goal) sera faite plus tard
    #   conjointement avec une mise à jour du frontend.
    task: str = Field(default="", description="canonical: question (intent)")
    goal: str = Field(default="", description="canonical: question (success criterion)")
    document_content: str = Field(default="", description="canonical: document")
    task_type: Literal["summary", "qa", "extraction"] | None = None
    # haystack mode discriminator. "sandbox" (default) uses document_content as
    # an ephemeral corpus; "benchmark" requires evaluation_query_id to look up
    # the canned task/goal from the catalog.
    haystack: Literal["benchmark", "sandbox"] = "sandbox"
    evaluation_query_id: str | None = None

    @model_validator(mode="after")
    def _validate_haystack_mode(self) -> "CompareRequest":
        if self.haystack == "benchmark":
            if not self.evaluation_query_id:
                raise ValueError("benchmark mode requires evaluation_query_id")
        else:  # sandbox
            if self.evaluation_query_id:
                raise ValueError("evaluation_query_id is only valid in benchmark mode")
            if not self.document_content.strip():
                raise ValueError("sandbox mode requires non-empty document_content")
        return self


class CompareResponse(BaseModel):
    """
    Blind comparison result.
    CRITICAL per UX-01: NO tool_id, NO server name, NO raw_result, NO endpoint.

    Canonical vocabulary :
      session_hash       -> comparison_id (à renommer avec migration DB)
      result_a / result_b -> answer_a / answer_b (à renommer avec frontend)
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
    name: str             # canonical: rag_tool.name
    description: str      # canonical: rag_tool.goal
    duration_ms: int
    error: str | None


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
    raw_sample: dict | None = None


class OAuthSeedRequest(BaseModel):
    server_id: str
    refresh_token: str
    access_token: str | None = None
    expires_in: int | None = None
