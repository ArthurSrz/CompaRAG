"""Regression test for production bug:

  rag_pill_query.failed engine_id=haystack exc_type=TypeError
  exc_msg="'NoneType' object is not subscriptable"

Reproduction:
- Beta-user uploads a 329 KB document for summary_default.
- OpenRouter routes embeddings to a degraded provider that returns a
  200 OK with a payload whose embedding values are None — not the
  empty-data shape the OpenAI SDK catches.
- Haystack's embedders propagate None embeddings downstream.
- The retriever tries to subscript a None embedding → TypeError.
- ``retry.execute_with_embedding_retry`` only retries on the
  ``ValueError("No embedding data received")`` marker, so the
  TypeError escapes immediately and reaches the user.

Fix: validate embedder output at the seam and convert silent
None payloads into the same ValueError marker, so the existing
retry mechanism handles them.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mcp_servers.rag_pill.retry import (
    _EMBEDDING_EMPTY_DATA_MARKER,
    execute_with_embedding_retry,
)


def _make_doc(content, meta=None, embedding=None):
    """Build a real haystack.Document so InMemoryDocumentStore accepts it."""
    from haystack import Document
    return Document(content=content, meta=meta or {}, embedding=embedding)


@pytest.mark.anyio
async def test_none_query_embedding_triggers_retry_marker_not_typeerror():
    """The user-visible bug: a haystack engine call where the *query*
    embedder returns ``{"embedding": None}`` must surface as the retry
    marker — not ``TypeError: 'NoneType' object is not subscriptable``."""
    haystack_engine = pytest.importorskip("mcp_servers.rag_pill.engines.haystack_engine")
    if not haystack_engine._AVAILABLE:
        pytest.skip("haystack not installed in this environment")

    from mcp_servers.rag_pill.cache import IndexCache
    from mcp_servers.rag_pill.providers import EmbeddingConfig
    from mcp_servers.rag_pill.schemas import SummaryPill

    class _CapturingLLM:
        async def invoke(self, pill, prompt):
            return "should not reach LLM when embedding is None"

    pill = SummaryPill(
        id="summary_default",
        name="Summary (default)",
        task_type="summary",
        embedder="text-embedding-3-small",
        chunk_size=500,
        chunk_overlap=50,
    )
    engine = haystack_engine.HaystackEngine(
        cache=IndexCache(),
        llm=_CapturingLLM(),
        embedding_config=EmbeddingConfig(
            provider_label="openrouter",
            api_key="sk-test",
            base_url="https://openrouter.ai/api/v1",
        ),
    )

    class _FakeDocEmbedder:
        def __init__(self, **_kw): ...
        def run(self, documents):
            # OpenRouter degraded shape: response shape preserved, embeddings None
            return {"documents": [_make_doc(d.content, d.meta, embedding=None) for d in documents]}

    class _FakeTextEmbedder:
        def __init__(self, **_kw): ...
        def run(self, text):
            return {"embedding": None}

    class _FakeSplitter:
        def __init__(self, **_kw): ...
        def warm_up(self): ...
        def run(self, documents):
            return {"documents": [_make_doc("chunk-1"), _make_doc("chunk-2")]}

    with patch.object(haystack_engine, "OpenAIDocumentEmbedder", _FakeDocEmbedder), \
         patch.object(haystack_engine, "OpenAITextEmbedder", _FakeTextEmbedder), \
         patch.object(haystack_engine, "DocumentSplitter", _FakeSplitter):
        with pytest.raises(ValueError, match=_EMBEDDING_EMPTY_DATA_MARKER):
            await execute_with_embedding_retry(
                engine,
                pill,
                task="summarise",
                goal="a clear summary",
                document_content="anything",
                max_retries=1,  # keep test fast
            )
