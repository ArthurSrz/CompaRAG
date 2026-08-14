"""
BUT : incarner l'InterviewProtocol de l'ontologie — les règles invariantes
de l'entretien (nombre max de tours, budget temps) appliquées PAR LE BACKEND
aux deux bras. Invariant d'équifinalité : les deux stratégies opèrent sous
les mêmes contraintes, la comparaison isole la qualité de la stratégie, pas
un avantage de ressources. C'est pourquoi ces règles ne vivent jamais dans
les outils eux-mêmes.
"""
from __future__ import annotations

import os
import time

# Nombre maximum de réponses de l'expert par bras.
INTERVIEW_MAX_TURNS = int(os.environ.get("INTERVIEW_MAX_TURNS", "10"))

# Budget temps de la session entière (les deux bras), en secondes.
INTERVIEW_TIME_BUDGET_S = int(os.environ.get("INTERVIEW_TIME_BUDGET_S", "900"))


def compute_deadline_ts(now: float | None = None) -> float:
    return (now if now is not None else time.time()) + INTERVIEW_TIME_BUDGET_S


def should_force_artifact(
    expert_answers: int,
    max_turns: int,
    deadline_ts: float,
    now: float | None = None,
) -> bool:
    """Vrai quand le protocole impose l'émission de l'artefact : le bras a
    consommé tous ses tours, ou la session a dépassé son budget temps."""
    current = now if now is not None else time.time()
    return expert_answers >= max_turns or current > deadline_ts


def transcript_to_markdown(transcript: list[dict]) -> str:
    """Rend le transcript d'un bras en markdown lisible — c'est le
    raw_result persisté dans tool_calls (l'Interview, variant intermédiaire),
    l'artefact étant le mediated_result."""
    lines: list[str] = []
    for entry in transcript:
        prefix = "**Q:**" if entry.get("role") == "interviewer" else "**A:**"
        lines.append(f"{prefix} {entry.get('content', '')}")
    return "\n\n".join(lines)
