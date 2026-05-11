"""ProgressEmitter — engines surface stage transitions for live UX.

Three load-bearing invariants this module guarantees:
1. NullEmitter accepts arbitrary kwargs without raising (engines that
   weren't given an emitter must not crash).
2. CollectingEmitter accumulates events in order (used by the rag_pill
   MCP server to serialize the per-side progress stream).
3. ThrottledEmitter drops ingest_progress events within a 500ms window
   so the UI isn't flooded when 1000+ documents stream in.
"""

import time
from unittest.mock import patch

from mcp_servers.rag_pill.progress import (
    CollectingEmitter,
    NullEmitter,
    ProgressEvent,
    ThrottledEmitter,
)


def test_null_emitter_accepts_arbitrary_kwargs() -> None:
    """Slice 6.1 — NullEmitter is the no-op default. Must accept any
    keyword shape an engine might emit without raising."""
    e = NullEmitter()
    e.emit("ingest_start")
    e.emit("ingest_progress", processed_docs=5, total_docs=18)
    e.emit("retrieval_done", span_count=3, took_ms=42, anything_else=True)


def test_collecting_emitter_accumulates_events_in_order() -> None:
    """Slice 6.2 — CollectingEmitter buffers events with the engine_id +
    pill_id stamped on each. Order matters: the MCP server replays them
    on the SSE stream in receive order."""
    e = CollectingEmitter(engine_id="chroma", pill_id="qa_precise")
    e.emit("ingest_start")
    e.emit("ingest_done", took_ms=120, cache_hit=False)
    e.emit("retrieval_done", span_count=3, took_ms=42)

    assert len(e.events) == 3
    assert [ev.type for ev in e.events] == [
        "ingest_start", "ingest_done", "retrieval_done",
    ]
    assert all(isinstance(ev, ProgressEvent) for ev in e.events)
    assert e.events[1].payload["took_ms"] == 120
    assert e.events[1].payload["cache_hit"] is False
    assert e.events[0].engine_id == "chroma"
    assert e.events[0].pill_id == "qa_precise"


def test_throttled_emitter_drops_ingest_progress_within_window() -> None:
    """Slice 6.3 — within a 500ms window, only the FIRST ingest_progress
    event reaches the inner emitter. Non-progress events bypass the
    throttle (we never miss an ingest_done or retrieval_start)."""
    inner = CollectingEmitter(engine_id="chroma", pill_id="qa_precise")

    fake_now = [0]

    def fake_time():
        return fake_now[0]

    with patch("mcp_servers.rag_pill.progress.time.time", side_effect=fake_time):
        throttled = ThrottledEmitter(inner, min_interval_ms=500)

        # Burst of progress events within 200ms — only first reaches inner.
        fake_now[0] = 1000.000
        throttled.emit("ingest_progress", processed_docs=1, total_docs=18)
        fake_now[0] = 1000.100
        throttled.emit("ingest_progress", processed_docs=5, total_docs=18)
        fake_now[0] = 1000.200
        throttled.emit("ingest_progress", processed_docs=12, total_docs=18)

        # A non-progress event in the same window passes through.
        throttled.emit("ingest_done", took_ms=300)

        # After the throttle window elapses, the next ingest_progress passes.
        fake_now[0] = 1000.700
        throttled.emit("ingest_progress", processed_docs=18, total_docs=18)

    types = [ev.type for ev in inner.events]
    assert types == ["ingest_progress", "ingest_done", "ingest_progress"]
    # First progress carried processed=1; second (after window) carried 18.
    progress_events = [ev for ev in inner.events if ev.type == "ingest_progress"]
    assert progress_events[0].payload["processed_docs"] == 1
    assert progress_events[1].payload["processed_docs"] == 18
