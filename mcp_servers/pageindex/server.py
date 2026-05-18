"""
BUT : exposer PageIndex (https://github.com/VectifyAI/PageIndex) comme un
RAGTool de l'arène. PageIndex est un RAG « vectorless » : il construit un
arbre hiérarchique (table-of-contents) du document et laisse un LLM
raisonner sur cet arbre pour répondre.

Architecture :
  1. document_content (texte/markdown) → fichier .md temporaire
  2. pageindex.page_index_md.md_to_tree(...) → arbre hiérarchique avec résumés
  3. LLM (via LiteLLM → OpenRouter) reçoit l'arbre + la question → réponse

Le package PageIndex upstream ne fournit ni setup.py ni pyproject.toml, il
est donc « vendored » comme submodule git sous ``vendor/PageIndex/`` et
ajouté à ``sys.path`` au chargement du module.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor" / "PageIndex"
if str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

from pageindex.page_index_md import md_to_tree  # noqa: E402

import litellm  # noqa: E402

litellm.drop_params = True

logging.basicConfig(level=logging.INFO, format="%(asctime)s [pageindex] %(message)s")
log = logging.getLogger("pageindex")

ARENA_MODEL = os.getenv(
    "PAGEINDEX_MODEL", "openrouter/mistralai/mistral-medium-3.1"
)
MAX_TOKENS = int(os.getenv("PAGEINDEX_MAX_TOKENS", "4096"))

mcp = FastMCP("PageIndex — vectorless reasoning RAG")


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


def _build_prompt(task: str, goal: str, tree: dict) -> str:
    tree_json = json.dumps(tree, ensure_ascii=False, indent=2)
    return (
        "You are answering a question by reasoning over a hierarchical "
        "tree index of a document (titles, summaries, and text per "
        "section). No vector search — navigate the tree by reasoning.\n\n"
        f"DOCUMENT TREE:\n{tree_json}\n\n"
        f"QUESTION: {task}\n"
        f"SUCCESS CRITERION: {goal}\n\n"
        "Answer the question using only the tree above. Be specific, "
        "cite section titles when relevant, and structure your answer "
        "clearly."
    )


def _run_pageindex_sync(document_content: str, task: str, goal: str) -> str:
    """Run the full PageIndex pipeline synchronously (called via to_thread)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(document_content)
        md_path = tmp.name

    try:
        tree = asyncio.run(
            md_to_tree(
                md_path=md_path,
                if_thinning=False,
                if_add_node_summary="yes",
                summary_token_threshold=200,
                model=ARENA_MODEL,
                if_add_doc_description="no",
                if_add_node_text="yes",
                if_add_node_id="yes",
            )
        )
        prompt = _build_prompt(task, goal, tree)
        response = litellm.completion(
            model=ARENA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=MAX_TOKENS,
        )
        return response.choices[0].message.content or ""
    finally:
        try:
            os.unlink(md_path)
        except OSError:
            pass


@mcp.tool()
async def rag_query(task: str, goal: str, document_content: str = "") -> str:
    """Answer a Question about a Document via PageIndex vectorless retrieval.

    Args:
        task: the user's instruction (canonical: question.intent).
        goal: the user's success criterion (canonical: question.success_criterion).
        document_content: uploaded Document text (markdown or plain text).

    Returns:
        The Answer as a plain string. Sanitization (BlindReveal) is applied
        by the backend before the user sees it.
    """
    if not document_content.strip():
        return "PageIndex requires document_content to build its tree index."

    t0 = time.time()
    try:
        answer = await asyncio.to_thread(
            _run_pageindex_sync, document_content, task, goal
        )
    except Exception as exc:
        log.warning(
            "pageindex.query.failed %s",
            json.dumps({
                "exc_type": type(exc).__name__,
                "exc_msg": str(exc)[:500],
                "doc_chars": len(document_content),
                "duration_ms": int((time.time() - t0) * 1000),
            }),
        )
        log.debug("pageindex.query.error", exc_info=exc)
        return f"PageIndex failed: {exc}"

    log.info(
        "pageindex.query %s",
        json.dumps({
            "model": ARENA_MODEL,
            "doc_chars": len(document_content),
            "answer_chars": len(answer),
            "duration_ms": int((time.time() - t0) * 1000),
        }),
    )
    return answer


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8013)),
        path="/mcp",
    )
