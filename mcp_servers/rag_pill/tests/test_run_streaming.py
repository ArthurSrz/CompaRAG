"""rag_pill /run-streaming — NDJSON stream of progress events + result/error.

Slices 6.6 + 6.7: a new HTTP endpoint that runs a single (pill, engine)
combination and streams progress events as the engine emits them, terminating
in a `{"type": "result", "result": EngineResult dict}` line on success or
`{"type": "error", "message": "..."}` on failure.

Tests don't spin up the full FastMCP app — they exercise the route handler
directly with a stub engine so the suite stays offline.
"""

import asyncio
import json

import pytest

from mcp_servers.rag_pill.engines.result import EngineResult, RetrievedSpan
from mcp_servers.rag_pill.run_streaming import build_ndjson_stream

pytestmark = pytest.mark.anyio


class _StubEngine:
    """Engine that emits a canned event sequence and returns a fixed EngineResult."""

    id = "stub"
    SUPPORTS = {"qa", "summary"}

    def __init__(self, *, raise_during_run: Exception | None = None):
        self._raise = raise_during_run

    async def execute_with_spans(self, pill, task, goal, *, corpus=None,
                                 document_content="", progress=None) -> EngineResult:
        emitter = progress
        emitter.emit("ingest_start")
        emitter.emit("ingest_done", cache_hit=False)
        emitter.emit("retrieval_start")
        emitter.emit("retrieval_done", took_ms=42)
        if self._raise:
            raise self._raise
        emitter.emit("mediation_start")
        emitter.emit("mediation_done", took_ms=1200)
        return EngineResult(
            answer="stub-answer",
            retrieved_spans=(
                RetrievedSpan("a.md", 0, 5, "hello", 0.9, 0),
            ),
            retrieval_latency_ms=42,
            generation_latency_ms=1200,
        )


async def _drain(stream) -> list[dict]:
    """Collect every NDJSON line into a list of parsed dicts."""
    out: list[dict] = []
    async for chunk in stream:
        for line in chunk.splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


async def test_run_streaming_emits_progress_then_result() -> None:
    """Slice 6.6 — happy path: stream yields ingest/retrieval/mediation
    events in order, terminating with a {type: 'result', result: {...}}
    line carrying the answer + retrieved_spans."""
    stub = _StubEngine()
    pill = object()  # not used by stub
    stream = build_ndjson_stream(
        engine=stub, pill=pill, engine_id="stub-engine", pill_id="stub-pill",
        task="t", goal="g", corpus=None, document_content="hi",
    )
    events = await _drain(stream)

    types = [e["type"] for e in events]
    assert types == [
        "ingest_start", "ingest_done", "retrieval_start", "retrieval_done",
        "mediation_start", "mediation_done", "result",
    ]
    # Each event carries engine_id + pill_id for the SSE handler downstream.
    assert events[0]["engine_id"] == "stub-engine"
    assert events[0]["pill_id"] == "stub-pill"
    # ingest_done carries the cache_hit flag.
    assert events[1].get("cache_hit") is False
    # Terminal result carries the EngineResult fields.
    result_event = events[-1]
    assert result_event["result"]["answer"] == "stub-answer"
    assert result_event["result"]["retrieval_latency_ms"] == 42
    assert result_event["result"]["generation_latency_ms"] == 1200
    assert len(result_event["result"]["retrieved_spans"]) == 1


async def test_run_streaming_yields_error_event_when_engine_raises() -> None:
    """Slice 6.7 — engine raises mid-run: stream terminates with a single
    {type: 'error', message: ...} event after whatever progress fired
    before the failure."""
    stub = _StubEngine(raise_during_run=RuntimeError("boom"))
    pill = object()
    stream = build_ndjson_stream(
        engine=stub, pill=pill, engine_id="stub-engine", pill_id="stub-pill",
        task="t", goal="g", corpus=None, document_content="hi",
    )
    events = await _drain(stream)

    types = [e["type"] for e in events]
    # Progress events fired before the raise -> retrieval_done was the last.
    assert types[-1] == "error"
    assert "boom" in events[-1]["message"]
    # No `result` event in the error path.
    assert "result" not in types
