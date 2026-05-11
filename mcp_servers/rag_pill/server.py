"""rag_pill MCP server — single endpoint dispatching (pill_id, engine_id) pairs."""

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, StreamingResponse

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
from mcp_servers.rag_pill.retry import execute_with_embedding_retry
from mcp_servers.rag_pill.run_streaming import build_ndjson_stream

logging.basicConfig(level=logging.INFO, format="%(asctime)s [rag-pill] %(message)s")
log = logging.getLogger("rag_pill")

PILLS_DIR = Path(__file__).parent / "pills"

cache = IndexCache(max_entries=32)
registry: PillRegistry | None = None
embed_cfg: EmbeddingConfig | None = None


@asynccontextmanager
async def lifespan(app):
    global registry, embed_cfg
    llm = OpenRouterLLM()
    embed_cfg = EmbeddingConfig.from_env()
    log.info(
        "embedding.config %s",
        json.dumps({"provider": embed_cfg.provider_label, "base_url": embed_cfg.base_url}),
    )
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
                "engine.disabled id=%s reason=framework_not_installed import_error=%s",
                engine.id,
                getattr(engine, "_import_error", "unknown"),
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
        answer = await execute_with_embedding_retry(
            engine, pill, task, goal, document_content
        )
    except Exception as exc:
        log.warning(
            "rag_pill_query.failed %s",
            json.dumps({
                "engine_id": engine_id,
                "pill_id": pill_id,
                "embedder": pill.embedder,
                "base_url": embed_cfg.base_url if embed_cfg else None,
                "provider": embed_cfg.provider_label if embed_cfg else None,
                "exc_type": type(exc).__name__,
                "exc_msg": str(exc)[:500],
                "doc_chars": len(document_content),
                "duration_ms": int((time.time() - t0) * 1000),
            }),
        )
        log.debug("rag_pill_query.error", exc_info=exc)
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


@mcp.custom_route("/run-streaming", methods=["POST"])
async def run_streaming(request: Request) -> StreamingResponse:
    """NDJSON stream of progress events + terminal result/error.

    Body: {pill_id, engine_id, task, goal, document_content?}
    Output: application/x-ndjson; one event per line:
      - {type: 'ingest_start' | 'ingest_done' | 'retrieval_*' | 'mediation_*', ...}
      - {type: 'result', result: {answer, retrieved_spans, ...}}
      - {type: 'error', message: '...'}

    Used by the backend tool_arena SSE handler (Phase 13 / Wave 6.8) to
    multiplex per-side progress into a single text/event-stream response
    to the frontend.
    """
    if registry is None:
        return JSONResponse({"error": "registry not ready"}, status_code=503)
    body = await request.json()
    try:
        pill = registry.get_pill(body["pill_id"])
        engine = registry.get_engine(body["engine_id"])
    except KeyError as exc:
        return JSONResponse(
            {"error": "unknown_pill_or_engine", "message": str(exc)},
            status_code=400,
        )

    if pill.task_type not in engine.SUPPORTS:
        return JSONResponse(
            {
                "error": "engine_unsupported_task_type",
                "message": (
                    f"Engine '{body['engine_id']}' does not support "
                    f"task_type '{pill.task_type}'."
                ),
            },
            status_code=400,
        )

    stream = build_ndjson_stream(
        engine=engine,
        pill=pill,
        engine_id=body["engine_id"],
        pill_id=body["pill_id"],
        task=body.get("task", ""),
        goal=body.get("goal", ""),
        document_content=body.get("document_content", ""),
    )
    return StreamingResponse(stream, media_type="application/x-ndjson")


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8012)),
        path="/mcp",
    )
