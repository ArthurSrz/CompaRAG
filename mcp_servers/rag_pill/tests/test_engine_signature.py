"""RAGEngine Protocol — signature drives Wave 2's engine refactor.

The Protocol's parameter name is the seam: callers (server.py, retry.py)
key off it. Slice 2.9 forces the rename document_content -> corpus on
the contract; slice 2.10 will follow with concrete engine updates.
"""

import inspect

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
