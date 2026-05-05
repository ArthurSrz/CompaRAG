"""rag_pill MCP server — single endpoint dispatching (pill_id, engine_id) pairs."""

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from mcp_servers.rag_pill.cache import IndexCache
from mcp_servers.rag_pill.engines import (
    ChromaBaselineEngine,
    HaystackEngine,
    LangChainEngine,
    LlamaIndexEngine,
    TxtaiEngine,
)
from mcp_servers.rag_pill.providers import EmbeddingConfig, OpenRouterLLM
from mcp_servers.rag_pill.registry import PillRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [rag-pill] %(message)s")
log = logging.getLogger("rag_pill")

PILLS_DIR = Path(__file__).parent / "pills"

cache = IndexCache(max_entries=32)
registry: PillRegistry | None = None


@asynccontextmanager
async def lifespan(app):
    global registry
    llm = OpenRouterLLM()
    embed_cfg = EmbeddingConfig.from_env()
    engines = [
        LangChainEngine(cache, llm=llm, embedding_config=embed_cfg),
        LlamaIndexEngine(cache, llm=llm, embedding_config=embed_cfg),
        HaystackEngine(cache, llm=llm, embedding_config=embed_cfg),
        TxtaiEngine(cache, llm=llm, embedding_config=embed_cfg),
        ChromaBaselineEngine(cache, llm=llm, embedding_config=embed_cfg),
    ]
    # Loud-WARN any engine whose framework failed to import — silent capability
    # loss skews arena fairness, so make it visible at startup.
    for engine in engines:
        if not engine.SUPPORTS:
            log.warning(
                "engine.disabled id=%s reason=framework_not_installed", engine.id
            )
    registry = PillRegistry(PILLS_DIR, engines)
    log.info(
        "registry.ready %s",
        json.dumps({"pills": registry.pill_ids, "engines": registry.engine_ids}),
    )
    yield


mcp = FastMCP("RAG Pill Dispatcher", lifespan=lifespan)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


@mcp.custom_route("/pills", methods=["GET"])
async def list_pills(request: Request) -> JSONResponse:
    if registry is None:
        return JSONResponse({"error": "registry not ready"}, status_code=503)
    return JSONResponse(
        {
            "pills": [
                registry.get_pill(pid).model_dump() for pid in registry.pill_ids
            ],
            "engines": [
                {"id": eid, "supports": sorted(registry.get_engine(eid).SUPPORTS)}
                for eid in registry.engine_ids
            ],
        }
    )


@mcp.tool()
async def rag_pill_query(
    pill_id: str,
    engine_id: str,
    task: str,
    goal: str,
    document_content: str = "",
) -> str:
    """Run a named pill on a chosen engine and return the synthesized answer."""
    if registry is None:
        return "Registry not ready, please retry shortly."
    try:
        pill = registry.get_pill(pill_id)
        engine = registry.get_engine(engine_id)
    except KeyError as exc:
        return f"Unknown pill or engine: {exc}"

    if pill.task_type not in engine.SUPPORTS:
        return f"Engine '{engine_id}' does not support task_type '{pill.task_type}'."

    t0 = time.time()
    try:
        answer = await engine.execute(pill, task, goal, document_content)
    except Exception as exc:
        log.exception("rag_pill_query.error")
        return f"Engine '{engine_id}' failed: {exc}"

    log.info(
        "rag_pill_query %s",
        json.dumps(
            {
                "pill": pill_id,
                "engine": engine_id,
                "task_type": pill.task_type,
                "doc_chars": len(document_content),
                "answer_chars": len(answer),
                "duration_ms": int((time.time() - t0) * 1000),
            }
        ),
    )
    return answer


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8012)),
        path="/mcp",
    )
