"""RAGEngine Protocol — signature drives Wave 2's engine refactor.

The Protocol's parameter name is the seam: callers (server.py, retry.py)
key off it. Slice 2.9 forces the rename document_content -> corpus on
the contract; slice 2.10 will follow with concrete engine updates.
"""

import inspect

import pytest

from mcp_servers.rag_pill.engines import (
    ChromaBaselineEngine,
    HaystackEngine,
    LangChainEngine,
    LlamaIndexEngine,
    TxtaiEngine,
)
from mcp_servers.rag_pill.engines.base import RAGEngine


def test_rag_engine_protocol_takes_corpus_not_document_content() -> None:
    """The Protocol must declare `corpus` as the haystack-source parameter,
    not the legacy `document_content` string. Engines accept a HaystackCorpus
    so they can serve both benchmark (FixedCorpus) and sandbox (EphemeralCorpus)
    traffic without per-call branching."""
    sig = inspect.signature(RAGEngine.execute)
    params = list(sig.parameters)

    assert "corpus" in params, f"missing 'corpus' param: {params}"
    assert "document_content" not in params, (
        f"legacy 'document_content' param still present: {params}"
    )


@pytest.mark.parametrize(
    "engine_cls",
    [
        ChromaBaselineEngine,
        HaystackEngine,
        LangChainEngine,
        LlamaIndexEngine,
        TxtaiEngine,
    ],
)
def test_concrete_engine_accepts_corpus_param(engine_cls) -> None:
    """Slice 2.10 — each concrete engine's execute() must accept a `corpus`
    kwarg. `document_content` stays as a back-compat kwarg during migration;
    a future slice removes it once retry.py + server.py + tests are updated."""
    sig = inspect.signature(engine_cls.execute)
    params = list(sig.parameters)
    assert "corpus" in params, (
        f"{engine_cls.__name__}.execute missing 'corpus' param: {params}"
    )
