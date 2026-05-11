"""tool-arena SSE streaming — multiplex two rag-pill /run-streaming NDJSON
streams into a single SSE response.

Wave 6.8: the /tool-arena/compare endpoint can return either:
  - application/json (CompareResponse, the sync path) — DEFAULT
  - text/event-stream (this module) — when Accept: text/event-stream

Each rag-pill emits NDJSON progress events; this module wraps each event
as an SSE `data:` line with pos="a"|"b" attached, so the frontend can
route per-side progress to two ProgressCards over a single EventSource.

After both sides emit their terminal `result` (or `error`), a single
`{type:"complete"}` event closes the SSE stream.

The httpx call to rag-pill lives in open_rag_pill_stream() so tests can
patch it without spinning up a real rag-pill container.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import httpx
from fastapi.responses import StreamingResponse

logger = logging.getLogger("languia")


def format_sse_event(data: Any) -> str:
    """Format a dict as a single SSE data line (terminated by blank line)."""
    return f"data: {json.dumps(data)}\n\n"


def _derive_streaming_url(endpoint: str) -> str:
    """Convert rag-pill's MCP endpoint (.../mcp) to its /run-streaming URL.

    rag-pill mounts both routes under the same FastMCP app, so swapping
    the path tail is sufficient. Idempotent if `/mcp` not present.
    """
    s = str(endpoint).rstrip("/")
    if s.endswith("/mcp"):
        return s[: -len("/mcp")] + "/run-streaming"
    return s + "/run-streaming"


async def open_rag_pill_stream(
    server,
    *,
    task: str,
    goal: str,
    document_content: str,
) -> AsyncIterator[dict]:
    """POST to a rag-pill server's /run-streaming and yield parsed NDJSON
    events as they arrive.

    Pulls pill_id / engine_id out of server.tool_args — that's the contract
    encoded in mcp_servers.json for rag-pill–backed contestants.
    """
    pill_id = server.tool_args.get("pill_id")
    engine_id = server.tool_args.get("engine_id")
    url = _derive_streaming_url(server.endpoint)

    payload = {
        "pill_id": pill_id,
        "engine_id": engine_id,
        "task": task,
        "goal": goal,
        "document_content": document_content,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=None)) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("rag-pill stream: malformed NDJSON line: %r", line[:200])


async def _tag_with_pos(
    stream: AsyncIterator[dict], pos: str
) -> AsyncIterator[dict]:
    async for event in stream:
        yield {**event, "pos": pos}


async def stream_compare(
    server_a,
    server_b,
    *,
    task: str,
    goal: str,
    document_content: str,
) -> AsyncIterator[str]:
    """Async generator yielding SSE-formatted lines for the /compare endpoint.

    Runs both rag-pill streams concurrently. Events are drained
    sequentially as they arrive so order reflects wall-clock arrival
    (not pos-a-then-pos-b). Terminates with a single {type:'complete'}.
    """
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def _drain(server, pos: str) -> None:
        try:
            async for event in _tag_with_pos(
                open_rag_pill_stream(
                    server, task=task, goal=goal, document_content=document_content
                ),
                pos,
            ):
                await queue.put(event)
        except Exception as exc:  # noqa: BLE001 — surface as terminal error event
            await queue.put({"type": "error", "pos": pos, "message": str(exc)})
        finally:
            await queue.put({"__done__": pos})

    drain_a = asyncio.create_task(_drain(server_a, "a"))
    drain_b = asyncio.create_task(_drain(server_b, "b"))
    done = {"a": False, "b": False}

    try:
        while not (done["a"] and done["b"]):
            event = await queue.get()
            if isinstance(event, dict) and "__done__" in event:
                done[event["__done__"]] = True
                continue
            yield format_sse_event(event)
        yield format_sse_event({"type": "complete"})
    finally:
        for t in (drain_a, drain_b):
            if not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass


def create_sse_response(generator: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
