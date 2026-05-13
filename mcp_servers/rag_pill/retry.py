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

# Default 4 retries (5 total attempts) with 1+2+4+8+16 = 31s window.
# Tunable via env for ops to dial down under quota pressure or up while a
# provider is flapping. The retries only fire on the marker errors below,
# so steady-state cost is zero — only flaky upstream pays.
EMBEDDING_RETRIES = int(os.environ.get("RAG_PILL_EMBEDDING_RETRIES", "4"))
_EMBEDDING_EMPTY_DATA_MARKER = "No embedding data received"


_NONETYPE_SUBSCRIPT_MARKER = "'NoneType' object is not subscriptable"


def _is_empty_embedding_data_error(exc: BaseException) -> bool:
    """True when the exception (or any of its __cause__/__context__ links)
    carries one of the OpenRouter-degradation marker strings.

    Two production traces share the same root cause (OpenRouter routes
    embedding traffic to a degraded provider that returns 200 with
    None-valued embeddings):

      - ``"No embedding data received"`` — the OpenAI SDK raises a
        ``ValueError`` with this message from openai/resources/embeddings.py
        when the ``data`` array is empty.
      - ``"'NoneType' object is not subscriptable"`` — when a None
        embedding leaks past the SDK and downstream code (haystack's
        retriever, llamaindex embedding fetch, langchain/FAISS subscript)
        indexes into it.

    We match by **message substring across any exception class** and walk
    the cause chain. Frameworks (haystack components, langchain runnables,
    llamaindex callbacks) sometimes wrap the original error in their own
    class while preserving the message verbatim — a class-strict matcher
    would miss those and turn one transient flake into a user-visible
    failure. The marker strings are specific enough that false positives
    are implausible.
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        msg = str(cur)
        if _EMBEDDING_EMPTY_DATA_MARKER in msg or _NONETYPE_SUBSCRIPT_MARKER in msg:
            return True
        cur = cur.__cause__ or cur.__context__
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
