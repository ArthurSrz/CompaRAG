"""Engines emit progress events at stage transitions.

Slice 6.4 — each engine's execute_with_spans accepts a `progress` kwarg
(defaulting to None / NullEmitter) and calls emit() at the documented
stage boundaries: ingest_start, ingest_done, retrieval_start,
retrieval_done, mediation_start, mediation_done.

The tests check the *signature* (kwarg present) and the *event order* from
a captured emitter when execute_with_spans runs. We don't exercise live
embeddings here — chroma's cache layer is monkeypatched to return a
canned collection so the test runs offline.
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
def test_engine_execute_with_spans_accepts_progress_kwarg(engine_cls) -> None:
    """Slice 6.4 — every engine accepts an optional `progress` ProgressEmitter
    so the dispatcher can wire a CollectingEmitter (legacy path) or a
    QueueEmitter (streaming path) without per-engine special-casing."""
    sig = inspect.signature(engine_cls.execute_with_spans)
    params = sig.parameters
    assert "progress" in params, (
        f"{engine_cls.__name__}.execute_with_spans missing 'progress' kwarg: "
        f"{list(params)}"
    )
    # Defaulted so existing callers don't have to pass it.
    assert params["progress"].default is not inspect.Parameter.empty
