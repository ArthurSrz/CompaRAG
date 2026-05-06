"""Retry behavior for the rag_pill server's embedding-failure escape hatch.

The OpenAI Python SDK raises ``ValueError("No embedding data received")``
when the embeddings response carries an empty ``data`` array — observed in
production as transient OpenRouter routing variance. Server wraps
``engine.execute`` in a bounded retry so a single user-facing call survives
a couple of these blips before the error message reaches the arena UI.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mcp_servers.rag_pill import retry as retry_module
from mcp_servers.rag_pill.retry import (
    _is_empty_embedding_data_error,
    execute_with_embedding_retry,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def no_sleep(monkeypatch):
    """Replace asyncio.sleep so retry tests don't actually wait."""
    async def _instant(_seconds):
        return None

    monkeypatch.setattr(retry_module.asyncio, "sleep", _instant)


class _ScriptedEngine:
    """Async engine stub that yields a scripted sequence of outcomes."""

    id = "scripted"

    def __init__(self, outcomes: list) -> None:
        # Each outcome is either an Exception (raised) or a string (returned).
        self._outcomes = list(outcomes)
        self.call_count = 0

    async def execute(self, pill, task, goal, document_content):
        self.call_count += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def fake_pill():
    return SimpleNamespace(embedder="openai/text-embedding-3-small")


# --- _is_empty_embedding_data_error ----------------------------------------


def test_marker_matches_exact_openai_sdk_message():
    assert _is_empty_embedding_data_error(ValueError("No embedding data received"))


def test_marker_matches_when_wrapped_in_context():
    assert _is_empty_embedding_data_error(
        ValueError("openai.embeddings.create: No embedding data received from upstream")
    )


def test_marker_rejects_unrelated_value_error():
    assert not _is_empty_embedding_data_error(ValueError("invalid model"))


def test_marker_rejects_non_value_error():
    assert not _is_empty_embedding_data_error(RuntimeError("No embedding data received"))


# --- execute_with_embedding_retry ------------------------------------------


async def test_retry_then_succeed(no_sleep, fake_pill):
    """Two transient empty-data failures, third attempt returns the answer."""
    engine = _ScriptedEngine([
        ValueError("No embedding data received"),
        ValueError("No embedding data received"),
        "the answer",
    ])
    out = await execute_with_embedding_retry(
        engine, fake_pill, "task", "goal", "doc", max_retries=2
    )
    assert out == "the answer"
    assert engine.call_count == 3


async def test_retry_exhausts_and_reraises(no_sleep, fake_pill):
    engine = _ScriptedEngine([
        ValueError("No embedding data received"),
        ValueError("No embedding data received"),
        ValueError("No embedding data received"),
    ])
    with pytest.raises(ValueError, match="No embedding data received"):
        await execute_with_embedding_retry(
            engine, fake_pill, "task", "goal", "doc", max_retries=2
        )
    assert engine.call_count == 3  # initial + max_retries


async def test_non_matching_exception_is_not_retried(no_sleep, fake_pill):
    """Auth/quota/etc. surface immediately — retrying would just delay the truth."""
    engine = _ScriptedEngine([
        RuntimeError("authentication failed: invalid API key"),
        "should never reach this",
    ])
    with pytest.raises(RuntimeError, match="authentication failed"):
        await execute_with_embedding_retry(
            engine, fake_pill, "task", "goal", "doc", max_retries=5
        )
    assert engine.call_count == 1


async def test_zero_retries_means_one_attempt(no_sleep, fake_pill):
    engine = _ScriptedEngine([ValueError("No embedding data received")])
    with pytest.raises(ValueError):
        await execute_with_embedding_retry(
            engine, fake_pill, "task", "goal", "doc", max_retries=0
        )
    assert engine.call_count == 1


def test_default_retries_reads_env(monkeypatch):
    """The module-level default reads RAG_PILL_EMBEDDING_RETRIES at import time."""
    import importlib

    monkeypatch.setenv("RAG_PILL_EMBEDDING_RETRIES", "5")
    reloaded = importlib.reload(retry_module)
    assert reloaded.EMBEDDING_RETRIES == 5
    # Restore default for subsequent tests in this session.
    monkeypatch.setenv("RAG_PILL_EMBEDDING_RETRIES", "2")
    importlib.reload(retry_module)
