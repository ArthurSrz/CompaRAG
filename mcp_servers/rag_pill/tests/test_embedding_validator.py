"""Tests for the embedder-output validator.

The validator sits between Haystack's OpenAI*Embedder components and the
rest of the engine. Its job: convert silent None-valued embeddings (a
degraded-OpenRouter symptom) into the same ``ValueError`` marker that
``retry.execute_with_embedding_retry`` already retries on.

Without it, a None embedding propagates downstream and surfaces as
``TypeError: 'NoneType' object is not subscriptable`` from haystack's
retriever — escaping the retry guard and reaching the user.
"""

from __future__ import annotations

import pytest

from mcp_servers.rag_pill.providers.embedding_validator import (
    validate_document_embeddings,
    validate_query_embedding,
)


class _Doc:
    """Stand-in for haystack.Document — only the .embedding attr is used."""

    def __init__(self, embedding):
        self.embedding = embedding


def test_validate_document_embeddings_passes_valid_output_through():
    docs = [_Doc([0.1, 0.2]), _Doc([0.3, 0.4])]
    result = {"documents": docs}

    out = validate_document_embeddings(result)

    assert out is result
    assert out["documents"] is docs


def test_validate_document_embeddings_raises_retry_marker_when_any_embedding_is_none():
    docs = [_Doc([0.1, 0.2]), _Doc(None), _Doc([0.5, 0.6])]
    result = {"documents": docs}

    with pytest.raises(ValueError, match="No embedding data received"):
        validate_document_embeddings(result)


def test_validate_query_embedding_passes_valid_output_through():
    result = {"embedding": [0.1, 0.2, 0.3]}

    out = validate_query_embedding(result)

    assert out is result


def test_validate_query_embedding_raises_retry_marker_when_embedding_is_none():
    result = {"embedding": None}

    with pytest.raises(ValueError, match="No embedding data received"):
        validate_query_embedding(result)


def test_validators_raise_retry_marker_when_whole_result_is_none():
    """Haystack components can return ``None`` outright on certain edge cases —
    that's the literal source of ``'NoneType' object is not subscriptable``."""
    with pytest.raises(ValueError, match="No embedding data received"):
        validate_document_embeddings(None)
    with pytest.raises(ValueError, match="No embedding data received"):
        validate_query_embedding(None)
