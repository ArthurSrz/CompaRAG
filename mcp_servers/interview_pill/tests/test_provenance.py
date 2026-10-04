"""Le livrable d'entretien mesure la CAPTURE, pas l'invention.

Bug d'origine (test utilisateur prod, 2026-10-03) : l'intervieweur « grill »
pose ses questions par rafales, chacune avec une réponse recommandée (➡️).
L'expert n'a répondu qu'à Q1–Q3 ; la synthèse a pourtant présenté les ➡️ de
Q4–Q7 (inspection des flaques, travaux récents, bruits anormaux, « quotidien
→ fuite franche ») comme la pratique de l'expert.

- Tests hors-ligne : la règle de provenance est bien dans le prompt système
  des deux stratégies et dans le bloc de fin forcée.
- Éval live (ANTHROPIC_API_KEY requis) : rejoue cet entretien et vérifie que
  les hypothèses non confirmées restent hors du corps du livrable.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # racine du repo
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-unused")

from mcp_servers.interview_pill import server  # noqa: E402

STRATEGIES = list(server.SKILLS)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_static_prompt_carries_provenance_rules(strategy):
    system = server._build_system(server.SKILLS[strategy], "t", "g", 1, 10, False)
    static = system[0]["text"]
    assert "PROVENANCE RULES" in static
    assert "CAPTURE, not invention" in static
    assert "TODO(provenance)" not in static


def test_forced_end_points_to_provenance_not_everything_gathered():
    block = server._session_block("t", "g", 4, 10, force_artifact=True)
    assert "PROVENANCE RULES" in block
    assert "everything gathered" not in block


# ── Éval live ────────────────────────────────────────────────────────────────

TASK = (
    "Je suis technicien de maintenance sur des chaudières industrielles à gaz. "
    "Je veux transmettre comment je diagnostique une perte de pression."
)
GOAL = "Rendre explicite ce que je sais mais n'ai jamais écrit"

ROUND_1 = """ROUND 1 - Contexte et déclenchement
❓ Q1 - Quand intervient le diagnostic ? Suite à une alarme, un appel, une inspection ?
➡️ Je suppose que c'est principalement suite à une alarme de pression basse.
❓ Q2 - Pression d'eau côté circuit ou pression de gaz ?
➡️ Je suppose qu'il s'agit de la pression d'eau du circuit de chauffage.
❓ Q3 - À partir de quelle valeur considérez-vous qu'il y a un problème ?
➡️ Je suppose qu'en dessous de 1 bar la chaudière se met en défaut."""

EXPERT_1 = (
    "Q1: surtout sur alarme basse pression ou appel de l'exploitant. "
    "Q2: pression d'eau côté circuit. "
    "Q3: alarme sous 1,2 bar, fonctionnement normal 1,5-2 bar à froid."
)

ROUND_2 = """ROUND 2 - Première approche
❓ Q4 - Que vérifiez-vous en arrivant sur site ?
➡️ Je suppose que vous lisez le manomètre puis cherchez des flaques d'eau autour de la chaudière.
❓ Q5 - Distinction perte lente vs rapide ?
➡️ Je suppose qu'une perte rapide oriente vers une fuite importante.
❓ Q6 - Questions à l'exploitant ?
➡️ Je suppose que vous demandez s'il y a eu des travaux récents et des bruits anormaux.
❓ Q7 - Fréquence de remise en pression ?
➡️ Je suppose que quotidien = fuite franche, mensuel = vase d'expansion."""

# Contenu présent UNIQUEMENT dans les ➡️ jamais confirmés (Q4–Q7).
UNCONFIRMED = [r"flaque", r"travaux récents", r"bruits? anormaux", r"fuite franche", r"manomètre"]


def _body(markdown: str) -> str:
    """Corps du livrable = tout ce qui précède la section des questions ouvertes."""
    m = re.search(r"^#+\s*questions? ouvertes?.*$", markdown, flags=re.I | re.M)
    return markdown[: m.start()] if m else markdown


@pytest.mark.skipif(
    os.environ.get("ANTHROPIC_API_KEY", "").startswith("test-key"),
    reason="éval live : nécessite ANTHROPIC_API_KEY",
)
@pytest.mark.anyio
@pytest.mark.parametrize("strategy", STRATEGIES)
async def test_unconfirmed_hypotheses_stay_out_of_the_body(strategy):
    transcript = [
        {"role": "interviewer", "content": ROUND_1},
        {"role": "expert", "content": EXPERT_1},
        {"role": "interviewer", "content": ROUND_2},
    ]
    raw = await server.interview_move(
        task=TASK, goal=GOAL, transcript=transcript,
        turn=2, max_turns=10, force_artifact=True, strategy=strategy,
    )
    move = json.loads(raw)
    assert move["type"] == "artifact", raw[:300]
    body = _body(move["artifact_markdown"]).lower()

    leaked = [p for p in UNCONFIRMED if re.search(p, body)]
    assert not leaked, f"hypothèses non confirmées dans le corps : {leaked}\n\n{body[:1500]}"
    assert "1,2" in body, "le seuil donné par l'expert (1,2 bar) doit être capturé"
