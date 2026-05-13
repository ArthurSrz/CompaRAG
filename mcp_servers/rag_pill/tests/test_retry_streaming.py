"""Retry coverage for the streaming path + TypeError-variant matcher.

Production report 2026-05-12: QA users see
  'Engine ⟨redacted⟩ failed: ‘NoneType’ object is not subscriptable'
after enabling the streaming path. Two gaps surface together:

  1. The retry wrapper in mcp_servers/rag_pill/retry.py only matches
     ``ValueError("No embedding data received")`` — the OpenAI SDK's
     symptom. The TypeError variant (raised when a None embedding leaks
     past the SDK and gets subscripted downstream) escapes the retry.

  2. The streaming path (run_streaming → engine.execute_with_spans) is
     not wrapped at all; legacy execute()-based flow goes through
     execute_with_embedding_retry but the new SSE path skips it.

These tests pin the fix:
  - retry matcher accepts the TypeError variant
  - execute_with_spans_with_retry wraps the streaming entrypoint
"""

from __future__ import annotations

import pytest

from mcp_servers.rag_pill.engines.result import EngineResult, RetrievedSpan
from mcp_servers.rag_pill.retry import (
    _is_empty_embedding_data_error,
    execute_with_spans_with_retry,
)

pytestmark = pytest.mark.anyio


def test_typeerror_nonetype_subscript_is_retried() -> None:
    """The retry matcher must recognize the TypeError variant.

    When a None embedding leaks past the SDK validator into downstream
    code that subscripts it (e.g. ``e["embedding"]``), the engine raises
    ``TypeError: 'NoneType' object is not subscriptable``. That is the
    SAME root cause as the SDK's ValueError; the retry wrapper must
    treat it the same.
    """
    assert _is_empty_embedding_data_error(
        TypeError("'NoneType' object is not subscriptable")
    ) is True


def test_other_typeerror_not_retried() -> None:
    """Don't widen too far — only the NoneType-subscript variant should
    match. A garden-variety TypeError (e.g. wrong arg count) must still
    propagate immediately so real bugs aren't masked by sleep loops."""
    assert _is_empty_embedding_data_error(
        TypeError("missing 2 required positional arguments")
    ) is False


def test_matcher_walks_cause_chain_for_framework_wrapped_marker() -> None:
    """Frameworks (haystack components, langchain runnables, llamaindex
    callbacks) sometimes re-raise the original TypeError as their own
    class while preserving the marker via ``raise … from original``. The
    matcher must walk ``__cause__`` so the same transient flake stays
    retry-eligible no matter who wraps it."""
    original = TypeError("'NoneType' object is not subscriptable")
    try:
        try:
            raise original
        except TypeError as exc:
            raise RuntimeError("haystack component failed") from exc
    except RuntimeError as wrapped:
        assert _is_empty_embedding_data_error(wrapped) is True


def test_matcher_walks_context_chain_for_implicit_wrap() -> None:
    """Implicit-chain variant: ``raise X`` inside an except without
    ``from`` populates ``__context__`` (not ``__cause__``). Same root
    cause; same retry decision."""
    try:
        try:
            raise TypeError("'NoneType' object is not subscriptable")
        except TypeError:
            raise RuntimeError("framework re-raise")
    except RuntimeError as wrapped:
        assert _is_empty_embedding_data_error(wrapped) is True


def test_matcher_handles_self_referential_cause_without_recursion() -> None:
    """Defensive: pathological exception graphs (cause loop) must not
    blow the stack. The matcher tracks visited ids and returns False
    when no marker is found along the chain."""
    e1 = RuntimeError("boring")
    e1.__cause__ = e1  # self-loop
    assert _is_empty_embedding_data_error(e1) is False


class _StubEngine:
    """Engine that fails N times with the production trace, then succeeds."""

    id = "stub"

    def __init__(self, fail_n: int, exc: Exception) -> None:
        self._fail_n = fail_n
        self._exc = exc
        self.calls = 0

    async def execute_with_spans(self, pill, task, goal, **kwargs) -> EngineResult:
        self.calls += 1
        if self.calls <= self._fail_n:
            raise self._exc
        return EngineResult(
            answer="ok",
            retrieved_spans=(RetrievedSpan("a.md", 0, 1, "h", 0.9, 0),),
            retrieval_latency_ms=10,
            generation_latency_ms=10,
        )


async def test_execute_with_spans_retry_recovers_from_typeerror_subscript() -> None:
    """Streaming path: when the engine raises the production TypeError on
    attempt 1, the retry wrapper retries and succeeds on attempt 2."""
    engine = _StubEngine(
        fail_n=1,
        exc=TypeError("'NoneType' object is not subscriptable"),
    )
    result = await execute_with_spans_with_retry(
        engine, pill=object(), task="t", goal="g", document_content="d",
        max_retries=2,
    )
    assert result.answer == "ok"
    assert engine.calls == 2


async def test_execute_with_spans_retry_recovers_from_valueerror_marker() -> None:
    """Same wrapper must still handle the original ValueError trace
    (haystack path) — widening the matcher must not regress it."""
    engine = _StubEngine(
        fail_n=1,
        exc=ValueError("No embedding data received"),
    )
    result = await execute_with_spans_with_retry(
        engine, pill=object(), task="t", goal="g", document_content="d",
        max_retries=2,
    )
    assert result.answer == "ok"
    assert engine.calls == 2


async def test_execute_with_spans_retry_gives_up_after_max_retries() -> None:
    """When the embedding flake persists across all attempts, the final
    exception propagates unchanged so the dispatcher can log it."""
    engine = _StubEngine(
        fail_n=10,
        exc=TypeError("'NoneType' object is not subscriptable"),
    )
    with pytest.raises(TypeError, match="NoneType"):
        await execute_with_spans_with_retry(
            engine, pill=object(), task="t", goal="g", document_content="d",
            max_retries=2,
        )
    # 1 initial + 2 retries = 3 attempts
    assert engine.calls == 3
