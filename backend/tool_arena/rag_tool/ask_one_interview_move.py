"""
BUT : jouer UN tour d'entretien avec UN outil de capture via MCP — la
primitive bas niveau de la boucle knowledge_capture. Frère de
ask_one_tool.py (même couture credential, session streamablehttp fraîche à
chaque appel), mais le contrat d'arguments est celui d'un entretien sans
état : transcript du bras + numéro de tour entrent, prochaine question ou
artefact final sort.

L'isolement des bras est structurel : chaque appel n'embarque QUE le
transcript de son propre bras (invariant ontologique — Interview est un
variant généré indépendamment par chaque outil).
"""
from __future__ import annotations

import json
import logging
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import TextContent

from backend.tool_arena.config import MCPServerConfig
from backend.tool_arena.credential import (
    CredentialError,
    OAuth2Credential,
    credential_for,
)
from backend.tool_arena.rag_tool.ask_one_tool import MCPToolError

logger = logging.getLogger("languia")


def parse_move(raw_text: str, force_artifact: bool) -> dict:
    """Parse tolérant du move renvoyé par l'outil.

    Un échec de parsing ne doit JAMAIS coûter son tour à l'expert : du texte
    non-JSON devient une question (ou l'artefact lui-même quand
    force_artifact est vrai). Un move {"type": "error"} émis par le serveur
    est promu en MCPToolError pour emprunter le chemin d'erreur existant.
    """
    text = raw_text.strip()
    try:
        move = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        move = None

    if isinstance(move, dict):
        if move.get("type") == "error":
            raise MCPToolError(str(move.get("error") or "interview tool error"))
        if move.get("type") == "question" and isinstance(move.get("question"), str):
            return {"type": "question", "question": move["question"]}
        if move.get("type") == "artifact" and isinstance(
            move.get("artifact_markdown"), str
        ):
            meta = move.get("metadata") if isinstance(move.get("metadata"), dict) else {}
            return {
                "type": "artifact",
                "artifact_markdown": move["artifact_markdown"],
                "artifact_subtype": meta.get("artifact_subtype"),
            }

    # Fallback tolérant — texte brut.
    if force_artifact:
        return {"type": "artifact", "artifact_markdown": text, "artifact_subtype": None}
    return {"type": "question", "question": text}


async def single_interview_move(
    server: MCPServerConfig,
    task: str,
    goal: str,
    transcript: list[dict],
    turn: int,
    max_turns: int,
    force_artifact: bool = False,
) -> tuple[dict, int]:
    """Open a fresh MCP session, play one interview move, return (move, duration_ms).

    Args:
        server: interview server config (tool_args carries the strategy).
        task: topic the expert claims expertise on (invariant).
        goal: what the captured knowledge must enable (invariant).
        transcript: THIS arm's conversation only —
            [{"role": "interviewer"|"expert", "content": str}, ...].
        turn: 1-based; expert answers so far + 1.
        max_turns: InterviewProtocol cap (backend-owned).
        force_artifact: True at cap/deadline/finish-early — artifact mandatory.

    Returns:
        ({"type": "question", "question": ...} |
         {"type": "artifact", "artifact_markdown": ..., "artifact_subtype": ...},
         duration_ms)

    Raises:
        MCPToolError: tool-level failure (isError=True or "type": "error").
        Exception: protocol/network failures — caller wraps with wait_for.
    """
    credential = credential_for(server)
    try:
        headers = await credential.headers_for(server)
    except CredentialError:
        raise

    auth = None
    if isinstance(credential, OAuth2Credential):
        auth = credential.provider_for(server)

    start = time.monotonic()
    async with streamablehttp_client(
        str(server.endpoint),
        headers=headers,
        auth=auth,
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tool_name = server.tools[0]
            arguments = {
                "task": task,
                "goal": goal,
                "transcript": transcript,
                "turn": turn,
                "max_turns": max_turns,
                "force_artifact": force_artifact,
                **server.tool_args,
            }
            result = await session.call_tool(tool_name, arguments=arguments)

            raw_text = "\n".join(
                c.text for c in result.content if isinstance(c, TextContent)
            )
            duration_ms = int((time.monotonic() - start) * 1000)

            if getattr(result, "isError", False):
                logger.warning(
                    "interview move returned isError=True server=%s turn=%d payload=%r",
                    server.id, turn, raw_text[:500],
                )
                raise MCPToolError(
                    raw_text or "tool returned isError=True with empty content"
                )

            move = parse_move(raw_text, force_artifact)
            logger.info(
                "interview move server=%s turn=%d type=%s duration_ms=%d",
                server.id, turn, move["type"], duration_ms,
            )
            return move, duration_ms
