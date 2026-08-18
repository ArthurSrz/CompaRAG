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
  3. La stratégie (grill | gsd_discuss) est un InterviewSkill (voir skills.py)
     chargé depuis skills.yaml au démarrage — plus une simple string.
     Le modèle est Anthropic Haiku 4.5 via SDK direct (pas OpenRouter/LiteLLM).

Prompt caching :
  - Le system prompt (skill.instructions + OUTPUT_CONTRACT + bloc session)
    est marqué cache_control=ephemeral → payé ~plein tarif au tour 1,
    puis ~0,1× aux tours 2-10 (TTL cache Anthropic ~5 min).
  - Le breakpoint de cache est déplacé au fur et à mesure du transcript :
    l'avant-dernier message est marqué ephemeral → les messages précédents
    sont servis depuis le cache au tour suivant.

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

import anthropic
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from mcp_servers.interview_pill.skills import SKILLS, InterviewSkill

logging.basicConfig(level=logging.INFO, format="%(asctime)s [interview] %(message)s")
log = logging.getLogger("interview_pill")

# LLMConstant : même modèle pour les deux stratégies (invariant d'équifinalité).
# Anthropic Haiku 4.5 en direct — plus rapide que LiteLLM/OpenRouter et éligible
# au prompt caching natif Anthropic (cache_control=ephemeral).
MODEL = os.getenv("INTERVIEW_LLM_ID", "claude-sonnet-4-5-20250929")
_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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


def _session_block(task: str, goal: str, turn: int, max_turns: int, force_artifact: bool) -> str:
    """Build the session-context block injected into the system prompt."""
    block = (
        "\n## Session (set by the arena backend — InterviewProtocol invariants)\n\n"
        f"- Topic the expert claims expertise on: {task}\n"
        f"- What the captured knowledge must enable: {goal}\n"
        f"- Expert answers so far: {turn - 1} of {max_turns} maximum.\n"
        "- LANGUAGE: conduct the ENTIRE interview — and write the final "
        "artifact — in the expert's language, i.e. the language of the topic "
        "and goal above (and of their answers). Never switch languages.\n"
    )
    if force_artifact:
        block += (
            "\nTHE INTERVIEW IS OVER. You MUST now emit the artifact JSON "
            '("type": "artifact") built from everything gathered so far, even '
            "if branches remain unexplored. Asking another question is a "
            "protocol violation.\n"
        )
    return block


def _build_system(
    skill: InterviewSkill,
    task: str,
    goal: str,
    turn: int,
    max_turns: int,
    force_artifact: bool,
) -> list[dict]:
    """Build the Anthropic system prompt with prompt caching enabled.

    The full system text (skill instructions + OUTPUT_CONTRACT + session block)
    is wrapped in a single text block marked cache_control=ephemeral.
    Anthropic caches this on the first call and serves it from cache on
    subsequent calls within the ~5-minute TTL — at 0.1× the input token price.
    """
    full_text = (
        skill.instructions
        + OUTPUT_CONTRACT
        + _session_block(task, goal, turn, max_turns, force_artifact)
    )
    return [{"type": "text", "text": full_text, "cache_control": {"type": "ephemeral"}}]


def _build_messages(
    transcript: list[dict],
    force_artifact: bool,
) -> list[dict]:
    """Convert the arm transcript to Anthropic message format.

    Cache breakpoint: the second-to-last message (the most recent already-seen
    exchange) is marked cache_control=ephemeral. On the next turn, all
    messages up to and including this breakpoint are served from the cache,
    so only the newest user message is billed at the full input token price.

    La liste DOIT se terminer par un tour user : un dernier message assistant
    (cas finish-early — le transcript finit sur une question de
    l'intervieweur) est traité comme un préfixe à continuer par le modèle,
    qui ré-émet alors sa question au lieu d'obéir au force_artifact système.
    """
    messages: list[dict] = []
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

    # Ensure last message is always from the user role.
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
    elif messages and messages[-1]["role"] == "assistant":
        messages.append(
            {
                "role": "user",
                "content": "(Continue the interview per your instructions.)",
            }
        )

    # Place cache breakpoint on second-to-last message so accumulated context
    # is cached on the next turn. Needs ≥2 messages and the cache target must
    # be a user message (Anthropic only caches at user-role turns).
    #
    # IMPORTANT: cache_control must live INSIDE a content block, not on the
    # message object itself. Placing it on the message causes a silent no-op
    # on short conversations and a 400 BadRequestError once message count
    # grows (Anthropic validates: "Extra inputs are not permitted").
    if len(messages) >= 2:
        idx = len(messages) - 2
        if messages[idx]["role"] == "user":
            raw_content = messages[idx]["content"]
            # Normalise to list-of-blocks so we can attach cache_control.
            if isinstance(raw_content, str):
                blocks: list[dict] = [{"type": "text", "text": raw_content}]
            elif isinstance(raw_content, list):
                blocks = list(raw_content)
            else:
                blocks = [{"type": "text", "text": str(raw_content)}]
            # Attach cache_control to the last block.
            blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
            messages[idx] = {**messages[idx], "content": blocks}

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


def _complete_sync(skill: InterviewSkill, system: list[dict], messages: list[dict]) -> str:
    """Call Anthropic API synchronously with prompt caching."""
    response = _client.messages.create(
        model=MODEL,
        max_tokens=skill.max_tokens,
        temperature=skill.temperature,
        system=system,
        messages=messages,
    )
    # Log cache usage to validate savings (visible in Railway logs).
    usage = response.usage
    log.info(
        "anthropic.usage input=%d output=%d cache_write=%d cache_read=%d",
        getattr(usage, "input_tokens", 0),
        getattr(usage, "output_tokens", 0),
        getattr(usage, "cache_creation_input_tokens", 0),
        getattr(usage, "cache_read_input_tokens", 0),
    )
    return response.content[0].text if response.content else ""


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
        strategy: which InterviewSkill drives this arm (via tool_args).

    Returns:
        JSON string: {"type":"question","question":...} or
        {"type":"artifact","artifact_markdown":...,"metadata":{...}}.
    """
    skill = SKILLS.get(strategy)
    if skill is None:
        return json.dumps(
            {"type": "error", "error": f"unknown strategy: {strategy}"},
            ensure_ascii=False,
        )

    transcript = transcript or []
    system = _build_system(skill, task, goal, turn, max_turns, force_artifact)
    messages = _build_messages(transcript, force_artifact)

    t0 = time.time()
    move: dict | None = None
    raw = ""
    try:
        for attempt in (1, 2):
            raw = await asyncio.to_thread(_complete_sync, skill, system, messages)
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
                "model": MODEL,
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
