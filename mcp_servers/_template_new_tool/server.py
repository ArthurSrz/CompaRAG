"""
BUT : squelette d'un nouveau RAGTool prêt à être adapté.

Pour créer un nouveau RAGTool :
    1. Copier ce dossier en mcp_servers/<slug_de_l_outil>/
    2. Renommer / adapter tool.manifest.yaml
    3. Remplacer la logique de `rag_query` ci-dessous par le vrai moteur
    4. Lancer `python scripts/register_tool.py <slug_de_l_outil>`
    5. Vérifier la suite de régression (`pytest backend/`) + le smoke test

La signature de `rag_query` est le contrat MCP de l'arène — ne pas la
changer sans coordination avec backend/tool_arena/rag_tool/ask_one_tool.py.
"""
from __future__ import annotations

import logging
import os

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [TEMPLATE_REPLACE_ME] %(message)s"
)
log = logging.getLogger("template_new_tool")

mcp = FastMCP("Template — change me")


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


@mcp.tool()
def rag_query(task: str, goal: str, document_content: str = "") -> str:
    """Answer a Question about a Document, in this tool's own way.

    Args:
        task: the user's instruction (canonical: question.intent).
        goal: the user's success criterion (canonical: question.success_criterion).
        document_content: optional uploaded Document text. If empty, fall back
            to the static Corpus.

    Returns:
        The Answer as a plain string. Sanitization (BlindReveal) is applied
        by the backend before the user sees it.
    """
    # TODO: replace this with the real RAG logic for the new tool.
    raise NotImplementedError(
        "TEMPLATE: implement rag_query for the new RAGTool. "
        "See mcp_servers/rag_pill/server.py for a reference."
    )


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8013)),
        path="/mcp",
    )
