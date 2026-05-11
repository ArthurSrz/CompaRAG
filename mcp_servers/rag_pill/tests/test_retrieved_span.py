"""EngineResult + RetrievedSpan — Wave 3 output contract.

Engines project their native chunk formats (Chroma docs, Haystack Documents,
LlamaIndex nodes, txtai rows, LangChain Documents) onto a comparable
RetrievedSpan unit so the arena can compute Recall@K / MRR / NDCG against
ExpectedSpan ground truth.

Both dataclasses are frozen — they flow through caches, asyncio.Queues, and
JSON serialization; mutation would silently corrupt audit trails.
"""

import dataclasses

import pytest

from mcp_servers.rag_pill.engines.result import EngineResult, RetrievedSpan


def test_retrieved_span_is_frozen() -> None:
    span = RetrievedSpan(
        source_doc_id="a.md",
        char_start=0,
        char_end=5,
        text="hello",
        score=0.9,
        rank=0,
    )
    assert dataclasses.is_dataclass(span)
    with pytest.raises(dataclasses.FrozenInstanceError):
        span.text = "tampered"  # type: ignore[misc]


def test_engine_result_is_frozen_and_carries_typed_fields() -> None:
    span = RetrievedSpan(
        source_doc_id="a.md", char_start=0, char_end=5,
        text="hello", score=None, rank=0,
    )
    result = EngineResult(
        answer="response",
        retrieved_spans=(span,),
        retrieval_latency_ms=42,
        generation_latency_ms=1200,
    )
    assert dataclasses.is_dataclass(result)
    assert result.retrieved_spans[0].text == "hello"
    assert result.unlocated_span_count == 0  # defaulted
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.answer = "tampered"  # type: ignore[misc]
