"""build_ndjson_stream — async iterable of NDJSON lines for /run-streaming.

Pure stream builder (no FastMCP / Starlette dependency) so it's testable
offline. The rag_pill server.py wires this into a Starlette StreamingResponse
on the /run-streaming custom_route.

Wire format: one JSON object per line, separated by '\\n'.
  - progress events (ingest_*, retrieval_*, mediation_*) with engine_id +
    pill_id + payload kwargs.
  - terminal `{type: 'result', result: EngineResult dict}` on success.
  - terminal `{type: 'error', message: str}` on engine exception.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass
from typing import Any, AsyncIterator

from mcp_servers.rag_pill.retry import execute_with_spans_with_retry


class _QueueEmitter:
    """Pushes ProgressEvents onto an asyncio.Queue as the engine emits."""

    def __init__(self, queue: asyncio.Queue, engine_id: str, pill_id: str) -> None:
        self._q = queue
        self.engine_id = engine_id
        self.pill_id = pill_id

    def emit(self, type: str, **payload) -> None:
        # put_nowait — engines emit from sync code paths inside run_in_executor;
        # the queue is unbounded so this never blocks.
        self._q.put_nowait(
            {"type": type, "engine_id": self.engine_id, "pill_id": self.pill_id, **payload}
        )


def _engine_result_to_dict(result: Any) -> dict:
    """Serialize EngineResult (frozen dataclass) into JSON-safe dict.
    retrieved_spans is a tuple of frozen RetrievedSpan dataclasses; asdict
    handles them recursively."""
    if is_dataclass(result):
        return asdict(result)
    # Fallback for stubs that already return dict-shaped data.
    return dict(result)


async def build_ndjson_stream(
    *,
    engine: Any,
    pill: Any,
    engine_id: str,
    pill_id: str,
    task: str,
    goal: str,
    corpus: Any = None,
    document_content: str = "",
) -> AsyncIterator[str]:
    """Async generator: yields NDJSON-encoded events as the engine runs.

    Drives engine.execute_with_spans on a background task, draining the
    QueueEmitter sequentially so events stream out in the order they fire.
    Terminates with a single `result` or `error` event.
    """
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    emitter = _QueueEmitter(queue, engine_id=engine_id, pill_id=pill_id)

    async def _runner() -> None:
        try:
            # Streaming path's twin of execute_with_embedding_retry —
            # OpenRouter occasionally returns 200 with None-valued
            # embeddings; the matcher catches both the SDK's
            # ValueError("No embedding data received") and its TypeError
            # leak-through variant.
            result = await execute_with_spans_with_retry(
                engine, pill, task, goal,
                document_content=document_content,
                corpus=corpus,
                progress=emitter,
            )
            await queue.put({"type": "result", "result": _engine_result_to_dict(result)})
        except Exception as exc:  # noqa: BLE001 — surface raw message to client
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)  # sentinel: drain complete

    task_handle = asyncio.create_task(_runner())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield json.dumps(event) + "\n"
    finally:
        if not task_handle.done():
            task_handle.cancel()
            try:
                await task_handle
            except (asyncio.CancelledError, Exception):
                pass
