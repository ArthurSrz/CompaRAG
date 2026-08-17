"""
BUT : exposer deux stratégies d'entretien (InterviewStrategy) comme
contestants « knowledge capture » de l'arène. Contrairement aux RAGTools
(document → réponse), un outil de capture interroge l'expert humain à tours
multiples puis produit un artefact de connaissance (KnowledgeArtifact).

Architecture — sans état (stateless) :
  1. Le backend possède la boucle de tours et l'état Redis (InterviewProtocol).
  2. Chaque appel `interview_move` reçoit le transcript complet DE CE BRAS
     uniquement + le numéro de tour, et rend soit la prochaine question,
     soit l'artefact final (JSON).
  3. La stratégie (grill | gsd_discuss) est le prompt système — le fichier
     d'instructions du skill d'origine, embarqué verbatim sous prompts/.
     Le modèle (LLMConstant, identique pour les deux bras) est exécuté via
     LiteLLM → OpenRouter.

Ontologie (goal_directed_action_ontology.json) : la stratégie est le VARIANT ;
l'expert, le protocole d'entretien et le LLM sont les INVARIANTS — c'est
pourquoi max_turns/force_artifact arrivent du backend et ne sont jamais
décidés ici.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import litellm
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

litellm.drop_params = True

logging.basicConfig(level=logging.INFO, format="%(asctime)s [interview] %(message)s")
log = logging.getLogger("interview_pill")

# LLMConstant : même modèle pour les deux stratégies (invariant d'équifinalité).
# Claude via OpenRouter — les skills sources ont été écrits pour Claude ;
# changeable via env var sans toucher au code.
ARENA_MODEL = os.getenv("INTERVIEW_LLM_ID", "openrouter/anthropic/claude-haiku-4.5")
MAX_TOKENS = int(os.getenv("INTERVIEW_MAX_TOKENS", "4096"))

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
STRATEGIES: dict[str, str] = {
    "grill": (_PROMPTS_DIR / "grill_strategy.md").read_text(encoding="utf-8"),
    "gsd_discuss": (_PROMPTS_DIR / "gsd_discuss_strategy.md").read_text(encoding="utf-8"),
}

# Contrat de sortie partagé — vit ici (et pas dans chaque fichier stratégie)
# pour que les deux bras ne puissent pas dériver l'un de l'autre.
OUTPUT_CONTRACT = """
## OUTPUT CONTRACT (mandatory)

Every response you produce MUST be a single JSON object, nothing else:

- To continue the interview:
  {"type": "question", "question": "<your next message to the expert, markdown allowed>"}
- To end the interview with the final deliverable:
  {"type": "artifact", "artifact_markdown": "<self-contained markdown document>",
   "metadata": {"artifact_subtype": "decision_rationale" | "procedural_know_how" | "mental_model"}}

Pick the artifact_subtype that best matches what the interview actually
surfaced. Never wrap the JSON in code fences or add text around it.

## Identity rules (mandatory)

You are one of several anonymous interviewers being blind-compared. Never
name your methodology, your source skill, your model, or your maker. Never
use the words that would identify you. If the expert asks who or what you
are, say only that you are an interviewer in a blind comparison.
"""

mcp = FastMCP("Interview Pill — knowledge capture strategies")


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


def _build_messages(
    strategy_prompt: str,
    task: str,
    goal: str,
    transcript: list[dict],
    turn: int,
    max_turns: int,
    force_artifact: bool,
) -> list[dict]:
    system = (
        f"{strategy_prompt}\n{OUTPUT_CONTRACT}\n"
        "## Session (set by the arena backend — InterviewProtocol invariants)\n\n"
        f"- Topic the expert claims expertise on: {task}\n"
        f"- What the captured knowledge must enable: {goal}\n"
        f"- Expert answers so far: {turn - 1} of {max_turns} maximum.\n"
        "- LANGUAGE: conduct the ENTIRE interview — and write the final "
        "artifact — in the expert's language, i.e. the language of the topic "
        "and goal above (and of their answers). Never switch languages.\n"
    )
    if force_artifact:
        system += (
            "\nTHE INTERVIEW IS OVER. You MUST now emit the artifact JSON "
            '("type": "artifact") built from everything gathered so far, even '
            "if branches remain unexplored. Asking another question is a "
            "protocol violation.\n"
        )
    messages: list[dict] = [{"role": "system", "content": system}]
    for entry in transcript:
        role = "assistant" if entry.get("role") == "interviewer" else "user"
        messages.append({"role": role, "content": str(entry.get("content", ""))})
    if not transcript:
        messages.append(
            {
                "role": "user",
                "content": (
                    "(The expert has joined the session. Open the interview "
                    "with your first message.)"
                ),
            }
        )
    # La liste DOIT se terminer par un tour user : un dernier message assistant
    # (cas finish-early — le transcript finit sur une question de
    # l'intervieweur) est traité comme un préfixe à continuer par le modèle,
    # qui ré-émet alors sa question au lieu d'obéir au force_artifact système.
    if force_artifact:
        messages.append(
            {
                "role": "user",
                "content": (
                    "(The interview has ended. Reply now with ONLY the "
                    "artifact JSON as specified in the OUTPUT CONTRACT — "
                    "no question, no other text.)"
                ),
            }
        )
    elif messages[-1]["role"] == "assistant":
        messages.append(
            {
                "role": "user",
                "content": "(Continue the interview per your instructions.)",
            }
        )
    return messages


def _parse_move(raw: str, force_artifact: bool) -> dict | None:
    """Retourne le move validé, ou None si le JSON est inexploitable."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        move = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(move, dict):
        return None
    if move.get("type") == "question" and isinstance(move.get("question"), str):
        # Sous force_artifact, une question est un refus d'obéir — la traiter
        # comme invalide déclenche la relance corrective puis le fallback.
        if force_artifact:
            return None
        return {"type": "question", "question": move["question"]}
    if move.get("type") == "artifact" and isinstance(move.get("artifact_markdown"), str):
        meta = move.get("metadata") if isinstance(move.get("metadata"), dict) else {}
        return {
            "type": "artifact",
            "artifact_markdown": move["artifact_markdown"],
            "metadata": {"artifact_subtype": meta.get("artifact_subtype")},
        }
    if force_artifact and isinstance(move.get("artifact_markdown"), str):
        return {
            "type": "artifact",
            "artifact_markdown": move["artifact_markdown"],
            "metadata": {"artifact_subtype": None},
        }
    return None


def _fallback_move(raw: str, force_artifact: bool) -> dict:
    """Dernier recours : le texte brut devient le move — jamais d'échec qui
    consommerait le tour de l'expert."""
    text = raw.strip()
    if force_artifact:
        # Si le refus était un JSON question, récupérer le texte utile plutôt
        # que d'emballer du JSON brut dans l'artefact.
        try:
            maybe = json.loads(text)
            if isinstance(maybe, dict) and isinstance(maybe.get("question"), str):
                text = maybe["question"]
        except (json.JSONDecodeError, ValueError):
            pass
        return {
            "type": "artifact",
            "artifact_markdown": text,
            "metadata": {"artifact_subtype": None},
        }
    return {"type": "question", "question": text}


def _complete_sync(messages: list[dict]) -> str:
    response = litellm.completion(
        model=ARENA_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or ""


@mcp.tool()
async def interview_move(
    task: str,
    goal: str,
    transcript: list[dict] | None = None,
    turn: int = 1,
    max_turns: int = 10,
    force_artifact: bool = False,
    strategy: str = "grill",
) -> str:
    """One stateless move of a knowledge-capture interview.

    Args:
        task: topic the expert claims expertise on (invariant, both arms).
        goal: what the captured knowledge must enable (invariant).
        transcript: THIS arm's conversation so far —
            [{"role": "interviewer"|"expert", "content": str}, ...].
        turn: 1-based; expert answers given so far + 1.
        max_turns: InterviewProtocol cap, decided by the backend.
        force_artifact: backend sets True at the cap/deadline/finish-early —
            the reply MUST be the artifact.
        strategy: which InterviewStrategy drives this arm (via tool_args).

    Returns:
        JSON string: {"type":"question","question":...} or
        {"type":"artifact","artifact_markdown":...,"metadata":{...}}.
    """
    strategy_prompt = STRATEGIES.get(strategy)
    if strategy_prompt is None:
        return json.dumps(
            {"type": "error", "error": f"unknown strategy: {strategy}"},
            ensure_ascii=False,
        )

    transcript = transcript or []
    messages = _build_messages(
        strategy_prompt, task, goal, transcript, turn, max_turns, force_artifact
    )

    t0 = time.time()
    move: dict | None = None
    raw = ""
    try:
        for attempt in (1, 2):
            raw = await asyncio.to_thread(_complete_sync, messages)
            move = _parse_move(raw, force_artifact)
            if move is not None:
                break
            # Une relance corrective, puis fallback tolérant — un échec de
            # parsing ne doit jamais coûter son tour à l'expert.
            messages = messages + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "(Invalid output — reply again with ONLY the JSON "
                        "object required by the OUTPUT CONTRACT.)"
                    ),
                },
            ]
        if move is None:
            move = _fallback_move(raw, force_artifact)
    except Exception as exc:
        log.warning(
            "interview.move.failed %s",
            json.dumps(
                {
                    "strategy": strategy,
                    "turn": turn,
                    "exc_type": type(exc).__name__,
                    "exc_msg": str(exc)[:500],
                    "duration_ms": int((time.time() - t0) * 1000),
                }
            ),
        )
        return json.dumps(
            {"type": "error", "error": f"interview move failed: {exc}"},
            ensure_ascii=False,
        )

    log.info(
        "interview.move %s",
        json.dumps(
            {
                "model": ARENA_MODEL,
                "strategy": strategy,
                "turn": turn,
                "max_turns": max_turns,
                "force_artifact": force_artifact,
                "move_type": move["type"],
                "duration_ms": int((time.time() - t0) * 1000),
            }
        ),
    )
    return json.dumps(move, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8014)),
        path="/mcp",
    )
