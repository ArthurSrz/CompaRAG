"""Regression: txtai engine must use external vectorization, not HF.

The bug: TxtaiEngine constructed Embeddings({"transform": fn, "content": True}),
which doesn't actually route through the transform — txtai falls back to its
default transformers backend and tries to load `pill.embedder` (e.g.
"openai/text-embedding-3-small") from the Hugging Face Hub, producing:

    OSError: openai/text-embedding-3-small is not a local folder and is not
    a valid model identifier listed on 'https://huggingface.co/models'

Fix: pass `"method": "external"` so txtai honours the transform callable.

This test exercises _build_index with a fake OpenAI client. If txtai falls
back to HF (the bug), the test errors at index time with the OSError above.
If the external method is wired correctly, the fake transform fn is called
and the index builds successfully.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from mcp_servers.rag_pill.cache import IndexCache
from mcp_servers.rag_pill.engines import TxtaiEngine
from mcp_servers.rag_pill.providers import EmbeddingConfig
from mcp_servers.rag_pill.schemas import QAPill


pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]


class _CapturingLLM:
    async def invoke(self, pill, prompt):
        return "ok"


def _fake_openai_response(inputs):
    """Deterministic 8-dim vectors; one per input."""
    data = []
    for i, _ in enumerate(inputs):
        v = np.zeros(8, dtype=np.float32)
        v[i % 8] = 1.0
        data.append(MagicMock(embedding=v.tolist()))
    return MagicMock(data=data)


async def test_txtai_uses_external_transform_not_hf():
    """Index builds via the OpenAI transform; no HF model load is attempted.

    The embedder name is "openai/text-embedding-3-small" — exactly the value
    that triggered the regression. If txtai tries to load it from HF, the
    test fails with OSError; if `method: external` is set, the fake transform
    is called and the index builds.
    """
    pill = QAPill(
        name="t",
        task_type="qa",
        embedder="openai/text-embedding-3-small",
        chunk_size=200,
        chunk_overlap=20,
        top_k=2,
        rerank=False,
        cite_sources=False,
        temperature=0.0,
    )
    engine = TxtaiEngine(
        cache=IndexCache(max_entries=2),
        llm=_CapturingLLM(),
        embedding_config=EmbeddingConfig(api_key="fake", base_url="https://fake"),
    )

    fake_client = MagicMock()
    fake_client.embeddings.create.side_effect = lambda model, input: _fake_openai_response(input)

    with patch("openai.OpenAI", return_value=fake_client):
        embeddings = await engine._build_index(
            pill,
            document_content="alpha bravo charlie. delta echo foxtrot. golf hotel.",
        )

    # The transform fn was actually called (proving txtai routed through external).
    assert fake_client.embeddings.create.called, (
        "txtai never called the OpenAI transform — it fell back to HF model loading"
    )
    # Index is queryable end-to-end.
    results = embeddings.search("alpha", 1)
    assert results, "txtai index has no rows after build"
