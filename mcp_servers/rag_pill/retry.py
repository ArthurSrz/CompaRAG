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


def _is_empty_embedding_data_error(exc: BaseException) -> bool:
    """True when the exception is the OpenAI SDK's empty-data ValueError.

    Matches by class + message rather than ``isinstance`` against the SDK
    type so we stay decoupled from the openai package version. The marker
    string comes from openai/resources/embeddings.py:116.
    """
    return isinstance(exc, ValueError) and _EMBEDDING_EMPTY_DATA_MARKER in str(exc)


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
