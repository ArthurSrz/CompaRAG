"""Boundary validator for Haystack embedder outputs.

Why this exists
---------------
Haystack's ``OpenAI*Embedder.run()`` returns a dict regardless of whether
the upstream embedding response was sane. When OpenRouter is degraded, it
sometimes returns 200 OK with a payload whose embedding values are
``None`` — neither raising the OpenAI SDK's ``ValueError("No embedding
data received")`` nor populating the embedding. The None silently
propagates into Haystack's retriever, which subscripts it and raises
``TypeError: 'NoneType' object is not subscriptable``.

By validating at the seam — immediately after every ``embedder.run()`` —
we convert that silent failure into the *same* ``ValueError`` marker that
``retry.execute_with_embedding_retry`` already retries on. The downstream
code paths and the retry machinery stay untouched.
"""

from __future__ import annotations

from typing import Any

# Must match retry._EMBEDDING_EMPTY_DATA_MARKER so the existing retry
# wrapper picks up these synthesized errors.
EMBEDDING_EMPTY_DATA_MARKER = "No embedding data received"


def _require(value: Any) -> Any:
    """Return ``value`` if it is not None, else raise the retry-marker error."""
    if value is None:
        raise ValueError(EMBEDDING_EMPTY_DATA_MARKER)
    return value


def validate_document_embeddings(result: Any) -> dict:
    """Return ``result`` unchanged if all documents have non-None embeddings.

    Raises ``ValueError(EMBEDDING_EMPTY_DATA_MARKER)`` when ``result`` is
    None / non-dict, lacks a ``documents`` key, or contains any document
    with ``embedding=None`` — so the existing retry wrapper picks it up.
    """
    payload = _require(result if isinstance(result, dict) else None)
    for doc in _require(payload.get("documents")):
        _require(getattr(doc, "embedding", None))
    return result


def validate_query_embedding(result: Any) -> dict:
    """Return ``result`` unchanged if the query embedding is non-None.

    Raises ``ValueError(EMBEDDING_EMPTY_DATA_MARKER)`` when ``result`` is
    None / non-dict, lacks an ``embedding`` key, or has ``embedding=None``
    — so the existing retry wrapper picks it up.
    """
    payload = _require(result if isinstance(result, dict) else None)
    _require(payload.get("embedding"))
    return result
