"""Backend /tool-arena/compare SSE handler — Wave 6.8 + 6.9.

Slice 6.8 — when the client sends Accept: text/event-stream, the endpoint
multiplexes two rag-pill /run-streaming NDJSON streams into a single SSE
response. Each event carries pos="a"|"b" so the frontend can route to
per-side ProgressCards. The stream terminates with a single
{type:"complete"} event.

Slice 6.9 — when the client sends Accept: application/json (or omits the
header), the endpoint returns the existing CompareResponse JSON blob
unchanged. The sync path must not regress.

Tests stub the per-server rag-pill stream at the streaming-module seam
(no httpx, no live rag-pill container).
"""

import json
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tool_arena.router import router

pytestmark = pytest.mark.anyio


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _make_fake_server(server_id: str, pill_id: str, engine_id: str):
    # Minimal stand-in for MCPServerConfig — only the attributes touched by
    # the streaming path. Avoids pulling the registry through the test.
    fake = MagicMock()
    fake.id = server_id
    fake.endpoint = f"http://localhost:8012/mcp"
    fake.tool_args = {"pill_id": pill_id, "engine_id": engine_id}
    fake.task_type = "qa"
    fake.llm_id = "test-llm"
    return fake


async def _canned_stream(events: list[dict]) -> AsyncIterator[dict]:
    for e in events:
        yield e


async def test_compare_streaming_emits_per_side_events_and_terminal_complete():
    """Slice 6.8 — SSE path multiplexes both rag-pill streams.

    Each NDJSON event from rag-pill is wrapped as an SSE `data:` line with
    pos="a"|"b" attached. After both streams emit their terminal `result`,
    a single `{type:"complete"}` event closes the SSE stream.
    """
    server_a = _make_fake_server("server-a", "qa_default", "langchain")
    server_b = _make_fake_server("server-b", "qa_default", "llamaindex")

    a_events = [
        {"type": "ingest_start", "engine_id": "langchain", "pill_id": "qa_default"},
        {"type": "ingest_done", "engine_id": "langchain", "pill_id": "qa_default", "cache_hit": False},
        {"type": "result", "result": {
            "answer": "Paris.",
            "retrieved_spans": [],
            "retrieval_latency_ms": 10,
            "generation_latency_ms": 200,
        }},
    ]
    b_events = [
        {"type": "ingest_start", "engine_id": "llamaindex", "pill_id": "qa_default"},
        {"type": "ingest_done", "engine_id": "llamaindex", "pill_id": "qa_default", "cache_hit": True},
        {"type": "result", "result": {
            "answer": "Paris.",
            "retrieved_spans": [],
            "retrieval_latency_ms": 5,
            "generation_latency_ms": 180,
        }},
    ]

    async def _fake_open_stream(server, *, task, goal, document_content):
        if server.id == "server-a":
            async for e in _canned_stream(a_events):
                yield e
        else:
            async for e in _canned_stream(b_events):
                yield e

    fake_disp_instance = MagicMock()
    fake_disp_instance.pick_pair = AsyncMock(return_value=(server_a, server_b))

    with patch(
        "backend.tool_arena.router.MCPDispatcher",
        return_value=fake_disp_instance,
    ), patch(
        "backend.tool_arena.comparison.stream_progress_to_browser.open_rag_pill_stream",
        side_effect=_fake_open_stream,
    ), patch(
        "backend.tool_arena.router.store_tool_session"
    ):
        client = TestClient(_app())
        response = client.post(
            "/tool-arena/compare",
            json={
                "task": "What is the capital of France?",
                "goal": "Answer concisely",
                "document_content": "Paris is the capital of France.",
                "task_type": "qa",
                "haystack": "sandbox",
            },
            headers={"Accept": "text/event-stream"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = []
    for line in response.text.split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))

    types_with_pos = [(e["type"], e.get("pos")) for e in events]
    # Both sides emit ingest_start + ingest_done + result; per-pos
    # interleaving may vary because the two streams race, but each side
    # MUST emit its three events in order.
    a_seq = [(t, p) for (t, p) in types_with_pos if p == "a"]
    b_seq = [(t, p) for (t, p) in types_with_pos if p == "b"]
    assert [t for (t, _) in a_seq] == ["ingest_start", "ingest_done", "result"]
    assert [t for (t, _) in b_seq] == ["ingest_start", "ingest_done", "result"]
    # Terminal event has no pos and is last.
    assert events[-1] == {"type": "complete"}


async def test_compare_sync_path_unchanged_without_sse_accept():
    """Slice 6.9 — without Accept: text/event-stream, the existing sync
    JSON path is unchanged. CompareResponse shape preserved."""
    server_a = _make_fake_server("server-a", "qa_default", "langchain")
    server_b = _make_fake_server("server-b", "qa_default", "llamaindex")

    from backend.tool_arena.models import MCPToolCall
    from datetime import datetime

    def _tc(server_id: str, answer: str) -> MCPToolCall:
        return MCPToolCall(
            call_id=f"call-{server_id}",
            session_id="sess-xyz",
            tool_id=server_id,
            llm_id="test-llm",
            task="What is the capital of France?",
            goal="Answer concisely",
            mediated_result=answer,
            raw_result=answer,
            duration_ms=200,
            created_at=datetime.now().isoformat(),
            error=None,
        )

    fake_disp_instance = MagicMock()
    fake_disp_instance.dispatch = AsyncMock(
        return_value=(_tc("server-a", "Paris."), _tc("server-b", "Paris."))
    )

    with patch(
        "backend.tool_arena.router.MCPDispatcher",
        return_value=fake_disp_instance,
    ), patch(
        "backend.tool_arena.router.store_tool_session"
    ), patch(
        "backend.tool_arena.router.save_tool_call_to_db"
    ):
        client = TestClient(_app())
        response = client.post(
            "/tool-arena/compare",
            json={
                "task": "What is the capital of France?",
                "goal": "Answer concisely",
                "document_content": "Paris is the capital of France.",
                "task_type": "qa",
                "haystack": "sandbox",
            },
            headers={"Accept": "application/json"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body.keys()) >= {"session_hash", "result_a", "result_b", "error_a", "error_b"}
    assert body["result_a"] == "Paris."
    assert body["result_b"] == "Paris."


async def test_stream_emits_keep_alive_during_quiet_phases(monkeypatch):
    """When both rag-pill streams go silent for longer than the heartbeat
    interval, stream_compare must emit `: keep-alive\n\n` SSE comment frames
    so browsers/edge proxies don't kill the connection mid-stream and surface
    the drop as `TypeError: Failed to fetch` on the client.

    Repro condition: chroma_baseline's first-time index of a 1MB doc takes
    ~60s emitting no per-event progress. Without keep-alive, Railway's edge
    closes the SSE connection at ~30s of idle.
    """
    import asyncio as _asyncio

    from backend.tool_arena.comparison import stream_progress_to_browser as streaming
    monkeypatch.setattr(streaming, "_SSE_HEARTBEAT_S", 0.05)

    async def _slow_stream():
        # Yield one event, then sleep long enough to provoke ≥2 heartbeats,
        # then yield a final result so the stream terminates cleanly.
        yield {"type": "ingest_start", "engine_id": "e", "pill_id": "p"}
        await _asyncio.sleep(0.18)
        yield {"type": "result", "result": {"answer": "x"}}

    server_a = _make_fake_server("srv-a", "p", "e")
    server_b = _make_fake_server("srv-b", "p", "e")

    with patch(
        "backend.tool_arena.comparison.stream_progress_to_browser.open_rag_pill_stream",
        side_effect=lambda *a, **kw: _slow_stream(),
    ):
        out: list[str] = []
        async for chunk in streaming.stream_compare(
            server_a, server_b,
            task="t", goal="g", document_content="d",
            session_hash="sh-test",
        ):
            out.append(chunk)

    keep_alives = [c for c in out if c.startswith(": keep-alive")]
    assert len(keep_alives) >= 1, f"expected ≥1 keep-alive frame, got {len(keep_alives)} (chunks: {out!r})"
    # Final completion event must still arrive.
    assert any('"type": "complete"' in c for c in out), out
