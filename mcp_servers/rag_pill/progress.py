"""ProgressEmitter — engines surface stage transitions for live UX.

Engines call emitter.emit(type, **payload) at key transitions:
  ingest_start / ingest_progress / ingest_done (with cache_hit flag)
  retrieval_start / retrieval_done
  mediation_start / mediation_done

The rag_pill MCP server collects these via CollectingEmitter and streams
them out as NDJSON; the backend tool_arena SSE handler reformats them as
text/event-stream events for the frontend ProgressCard.

NullEmitter is the default for tests + non-streaming callers — engines must
never crash when no emitter is wired.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ProgressEvent:
    type: str
    engine_id: str | None = None
    pill_id: str | None = None
    payload: dict = field(default_factory=dict)
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))


class ProgressEmitter(Protocol):
    def emit(self, type: str, **payload) -> None: ...


class NullEmitter:
    """No-op default. Engines accept emitter=None and substitute this."""

    def emit(self, type: str, **payload) -> None:
        pass


class CollectingEmitter:
    """Accumulates events in receive order with engine_id + pill_id stamp.

    The rag_pill MCP server uses this when the request did NOT come via the
    streaming endpoint — events go into the response envelope for legacy
    clients. The streaming endpoint uses a QueueEmitter instead (defined in
    server.py to keep the asyncio.Queue out of this pure module).
    """

    def __init__(self, engine_id: str, pill_id: str) -> None:
        self.engine_id = engine_id
        self.pill_id = pill_id
        self.events: list[ProgressEvent] = []

    def emit(self, type: str, **payload) -> None:
        self.events.append(
            ProgressEvent(
                type=type,
                engine_id=self.engine_id,
                pill_id=self.pill_id,
                payload=payload,
            )
        )


class ThrottledEmitter:
    """Wraps another emitter and drops ingest_progress events within a
    window so the UI isn't flooded by 1000-document corpus ingest streams.

    Non-progress events bypass the throttle entirely — we never miss an
    ingest_done, retrieval_start, etc. Only ingest_progress is rate-limited.
    """

    def __init__(self, inner: ProgressEmitter, min_interval_ms: int = 500) -> None:
        self._inner = inner
        self._min = min_interval_ms
        self._last_progress_ms: int = 0

    def emit(self, type: str, **payload) -> None:
        if type == "ingest_progress":
            now_ms = int(time.time() * 1000)
            if now_ms - self._last_progress_ms < self._min:
                return
            self._last_progress_ms = now_ms
        self._inner.emit(type, **payload)
