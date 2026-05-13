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

from typing import Any, Iterable

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


def validate_vector_list(vectors: Any) -> list:
    """Materialize ``vectors`` into a list and raise the empty-data marker
    if any entry is None or empty.

    Used by engines that do their own pre-embedding step (langchain,
    llamaindex, chroma) before handing vectors to a framework constructor
    that would otherwise subscript a None deep inside its vector ops and
    raise an opaque TypeError. Routing the failure through this single
    marker means the existing retry wrapper picks it up and the engine
    surfaces the same friendly retry behavior the haystack/txtai paths
    already have.

    Returns the materialized list (top-level only) with the original
    inner vectors preserved as-is. Chromadb's `OpenAIEmbeddingFunction`
    returns `list[np.float32]`-shaped inner vectors and rejects anything
    cast through Python `float`, so the inner type must round-trip
    untouched.
    """
    out: list = []
    for vec in vectors:
        if vec is None:
            raise ValueError(EMBEDDING_EMPTY_DATA_MARKER)
        try:
            n = len(vec)
        except TypeError as exc:
            raise ValueError(EMBEDDING_EMPTY_DATA_MARKER) from exc
        if n == 0:
            raise ValueError(EMBEDDING_EMPTY_DATA_MARKER)
        out.append(vec)
    return out


def validate_query_embedding(result: Any) -> dict:
    """Return ``result`` unchanged if the query embedding is non-None.

    Raises ``ValueError(EMBEDDING_EMPTY_DATA_MARKER)`` when ``result`` is
    None / non-dict, lacks an ``embedding`` key, or has ``embedding=None``
    — so the existing retry wrapper picks it up.
    """
    payload = _require(result if isinstance(result, dict) else None)
    _require(payload.get("embedding"))
    return result
