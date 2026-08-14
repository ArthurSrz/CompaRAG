"""
BUT : décrire les contrats HTTP de la boucle d'entretien knowledge_capture.
Comme comparison/contracts.py : pas de logique métier, juste des Pydantic
models. Aveugle par construction (UX-01) : aucun tool_id, aucun nom de
stratégie, aucun endpoint ne sort par ces contrats.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class InterviewStartRequest(BaseModel):
    # Canonical vocabulary : task + goal sont les deux moitiés de la
    # `question` du domaine — ici le sujet d'expertise et ce que la
    # connaissance capturée doit permettre.
    task: str = Field(description="canonical: question (topic of expertise)")
    goal: str = Field(description="canonical: question (what the knowledge must enable)")

    @model_validator(mode="after")
    def _require_non_empty(self) -> "InterviewStartRequest":
        if not self.task.strip():
            raise ValueError("task must be non-empty")
        if not self.goal.strip():
            raise ValueError("goal must be non-empty")
        return self


class ArmState(BaseModel):
    """État visible d'un bras — la question courante, jamais l'artefact
    (il n'apparaît qu'au finalize, une fois sanitisé)."""

    type: Literal["question", "artifact", "error"]
    question: str | None = None
    turn: int  # réponses de l'expert données sur ce bras
    max_turns: int
    done: bool = False
    error: str | None = None  # message générique — jamais le détail interne


class InterviewStartResponse(BaseModel):
    session_hash: str = Field(description="canonical: comparison_id")
    max_turns: int
    deadline_ts: float
    arm_a: ArmState
    arm_b: ArmState


class InterviewReplyRequest(BaseModel):
    arm: Literal["a", "b"]
    answer: str

    @model_validator(mode="after")
    def _require_answer(self) -> "InterviewReplyRequest":
        if not self.answer.strip():
            raise ValueError("answer must be non-empty")
        return self


class InterviewFinishRequest(BaseModel):
    arm: Literal["a", "b"]


class InterviewReplyResponse(BaseModel):
    arm: Literal["a", "b"]
    state: ArmState
    both_done: bool = False
