"""Bounded-retry wrapper for engine.execute().

Production sees recurring ``ValueError("No embedding data received")`` from
the OpenAI Python SDK whenever an embeddings response carries an empty
``data`` array — symptom of OpenRouter occasionally routing embedding
traffic to a provider that returns 200 with no payload. The cheapest fix
that keeps every engine untouched is a coarse retry at the call site.

Design mirrors backend/tool_arena/dispatcher.py:202-250
(``_call_with_resilience``): bounded attempts, exponential backoff, no
retry on non-matching exceptions so auth/quota/timeout surface immediately
instead of being delayed by sleep loops.

Lives in its own module so unit tests can import it without pulling
``fastmcp`` (a runtime-only dependency of server.py).
"""

from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger("rag_pill")

# Default 2 retries (3 total attempts) with 1s, 2s backoff. Tunable via env
# for ops to dial down under quota pressure or up while a provider is
# flapping.
EMBEDDING_RETRIES = int(os.environ.get("RAG_PILL_EMBEDDING_RETRIES", "2"))
_EMBEDDING_EMPTY_DATA_MARKER = "No embedding data received"


_NONETYPE_SUBSCRIPT_MARKER = "'NoneType' object is not subscriptable"


def _is_empty_embedding_data_error(exc: BaseException) -> bool:
    """True when the exception is the OpenAI SDK's empty-data ValueError
    OR its TypeError leak-through variant.

    Two production traces share the same root cause (OpenRouter routes
    embedding traffic to a degraded provider that returns 200 with
    None-valued embeddings):

      - ``ValueError("No embedding data received")`` — the OpenAI SDK
        raises this from openai/resources/embeddings.py:116 when the
        ``data`` array is empty.
      - ``TypeError("'NoneType' object is not subscriptable")`` — when
        a None embedding leaks past the SDK and downstream code (e.g.
        haystack's retriever, llamaindex embedding fetch) subscripts it.

    Both signal the same transient upstream flake; both should retry.
    We match by class + message rather than ``isinstance`` against the
    SDK types so we stay decoupled from openai package versions.
    """
    if isinstance(exc, ValueError) and _EMBEDDING_EMPTY_DATA_MARKER in str(exc):
        return True
    if isinstance(exc, TypeError) and _NONETYPE_SUBSCRIPT_MARKER in str(exc):
        return True
    return False


async def execute_with_embedding_retry(
    engine,
    pill,
    task: str,
    goal: str,
    document_content: str,
    *,
    max_retries: int | None = None,
) -> str:
    """Run ``engine.execute`` with bounded retry on empty-embedding-data errors."""
    retries = EMBEDDING_RETRIES if max_retries is None else max_retries
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await engine.execute(pill, task, goal, document_content)
        except Exception as exc:
            if not _is_empty_embedding_data_error(exc):
                raise
            last_exc = exc
            if attempt >= retries:
                break
            backoff_s = 2 ** attempt
            log.warning(
                "embedding.empty_data engine=%s attempt=%d/%d backoff_s=%d",
                engine.id, attempt + 1, retries + 1, backoff_s,
            )
            await asyncio.sleep(backoff_s)
    assert last_exc is not None
    raise last_exc


async def execute_with_spans_with_retry(
    engine,
    pill,
    task: str,
    goal: str,
    document_content: str,
    *,
    progress=None,
    corpus=None,
    max_retries: int | None = None,
):
    """Streaming-path twin of ``execute_with_embedding_retry``.

    The legacy ``rag_pill_query`` MCP tool wraps ``engine.execute()`` in
    ``execute_with_embedding_retry``. The streaming path
    (``run_streaming.build_ndjson_stream``) drives ``execute_with_spans``
    directly, bypassing that guard. This wrapper applies the same
    bounded retry on the same matcher, returning the full ``EngineResult``
    instead of just ``.answer``.

    Shape mirrors execute_with_embedding_retry: same backoff schedule,
    same warning log, same final-raise semantics.
    """
    retries = EMBEDDING_RETRIES if max_retries is None else max_retries
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await engine.execute_with_spans(
                pill, task, goal,
                document_content=document_content,
                corpus=corpus,
                progress=progress,
            )
        except Exception as exc:
            if not _is_empty_embedding_data_error(exc):
                raise
            last_exc = exc
            if attempt >= retries:
                break
            backoff_s = 2 ** attempt
            log.warning(
                "embedding.empty_data engine=%s attempt=%d/%d backoff_s=%d path=streaming",
                engine.id, attempt + 1, retries + 1, backoff_s,
            )
            await asyncio.sleep(backoff_s)
    assert last_exc is not None
    raise last_exc
