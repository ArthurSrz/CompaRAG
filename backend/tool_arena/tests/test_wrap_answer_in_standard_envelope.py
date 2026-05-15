"""Unit tests for the output normalizer module (D-04 through D-07)."""

import json
import pytest

from backend.tool_arena.answer.wrap_answer_in_standard_envelope import (
    NormalizedEnvelope,
    RetrievedSpanEnvelope,
    Source,
    normalize_output,
)


def test_normalizer_passes_through_retrieved_spans():
    """Slice 3.11 — when the MCP tool's raw envelope carries retrieved_spans
    (Phase 13 / Wave 3 needle-in-haystack output), the normalizer preserves
    them in NormalizedEnvelope.retrieved_spans. Score, char range, rank, and
    text all survive intact for the RetrievalJudge (plan 13-05)."""
    raw = json.dumps({
        "answer": "Paris.",
        "retrieved_spans": [
            {
                "source_doc_id": "geography_fr.md",
                "char_start": 1245,
                "char_end": 1389,
                "text": "Paris est la capitale de la France.",
                "score": 0.92,
                "rank": 0,
            },
            {
                "source_doc_id": "geography_fr.md",
                "char_start": 2100,
                "char_end": 2156,
                "text": "Tour Eiffel.",
                "score": 0.71,
                "rank": 1,
            },
        ],
        "retrieval_latency_ms": 42,
        "generation_latency_ms": 1200,
    })
    result = normalize_output(raw, duration_ms=2000)

    assert result.answer == "Paris."
    assert len(result.retrieved_spans) == 2
    first = result.retrieved_spans[0]
    assert isinstance(first, RetrievedSpanEnvelope)
    assert first.source_doc_id == "geography_fr.md"
    assert (first.char_start, first.char_end) == (1245, 1389)
    assert first.text.startswith("Paris est")
    assert first.score == 0.92
    assert first.rank == 0
    assert result.retrieval_latency_ms == 42
    assert result.generation_latency_ms == 1200
    # retrieved_spans was supplied, so it must NOT be flagged as defaulted
    assert "retrieved_spans" not in result.normalized_fields


def test_normalizer_defaults_retrieved_spans_when_absent():
    """Legacy tools that don't surface retrieved_spans get an empty list
    and a 'retrieved_spans' entry in normalized_fields — the judge can
    then distinguish 'tool retrieved 0 chunks' from 'tool doesn't surface
    retrieval at all' (sandbox-only summary engines, third-party MCPs)."""
    raw = json.dumps({"answer": "hi", "sources": [], "confidence": 0.5, "latency_ms": 10})
    result = normalize_output(raw, duration_ms=10)

    assert result.retrieved_spans == []
    assert "retrieved_spans" in result.normalized_fields


# --------------------------------------------------------------------------- #
# Tests: normalize_output
# --------------------------------------------------------------------------- #

def test_full_envelope_passes_through():
    """Test 1: normalize_output with full envelope passes through unchanged, normalized_fields=[]."""
    raw = json.dumps({
        "answer": "The answer is 42.",
        "sources": [{"url": "https://example.com", "title": "Example", "snippet": "text", "page": 1}],
        "confidence": 0.95,
        "latency_ms": 120,
    })
    result = normalize_output(raw, duration_ms=150)
    assert result.answer == "The answer is 42."
    assert len(result.sources) == 1
    assert result.sources[0].url == "https://example.com"
    assert result.confidence == 0.95
    assert result.latency_ms == 120
    # The pre-Phase-13 envelope didn't supply retrieved_spans /
    # retrieval_latency_ms / generation_latency_ms — they're defaulted.
    assert set(result.normalized_fields) == {
        "retrieved_spans", "retrieval_latency_ms", "generation_latency_ms",
    }


def test_missing_confidence_defaulted():
    """Test 2: normalize_output with missing confidence returns confidence=None, normalized_fields=['confidence']."""
    raw = json.dumps({
        "answer": "Something happened.",
        "sources": [],
        "latency_ms": 50,
    })
    result = normalize_output(raw, duration_ms=80)
    assert result.confidence is None
    assert "confidence" in result.normalized_fields


def test_missing_sources_defaulted():
    """Test 3: normalize_output with missing sources returns sources=[], normalized_fields=['sources']."""
    raw = json.dumps({
        "answer": "Short answer.",
        "confidence": 0.8,
        "latency_ms": 30,
    })
    result = normalize_output(raw, duration_ms=40)
    assert result.sources == []
    assert "sources" in result.normalized_fields


def test_plain_string_answer():
    """Test 4: normalize_output with plain string (no JSON envelope) wraps entire text as answer."""
    raw = "This is a plain text answer."
    result = normalize_output(raw, duration_ms=200)
    assert result.answer == "This is a plain text answer."
    assert result.sources == []
    assert result.confidence is None
    assert result.latency_ms == 200  # defaults to duration_ms
    assert "sources" in result.normalized_fields
    assert "confidence" in result.normalized_fields
    assert "latency_ms" in result.normalized_fields


def test_json_without_answer_key():
    """Test 5: normalize_output with JSON but no 'answer' key treats entire text as plain string."""
    raw = json.dumps({"result": "something", "status": "ok"})
    result = normalize_output(raw, duration_ms=100)
    assert "result" in result.answer or raw in result.answer  # whole raw becomes answer
    assert result.sources == []


def test_source_object_fields():
    """Test 6: Source objects have url, title, snippet, page fields (all optional)."""
    s = Source()
    assert s.url is None
    assert s.title is None
    assert s.snippet is None
    assert s.page is None

    s2 = Source(url="https://example.com", title="Test", snippet="A snippet", page=3)
    assert s2.url == "https://example.com"
    assert s2.page == 3


def test_latency_ms_from_json_takes_priority():
    """Test 7: If latency_ms is in JSON, it takes priority over duration_ms param."""
    raw = json.dumps({
        "answer": "Test answer.",
        "sources": [],
        "confidence": 0.9,
        "latency_ms": 75,
    })
    result = normalize_output(raw, duration_ms=999)
    assert result.latency_ms == 75
    assert "latency_ms" not in result.normalized_fields


def test_missing_latency_uses_duration_ms():
    """Test 8: If latency_ms is missing from JSON, duration_ms parameter is used."""
    raw = json.dumps({
        "answer": "Another answer.",
        "sources": [],
        "confidence": 0.7,
    })
    result = normalize_output(raw, duration_ms=333)
    assert result.latency_ms == 333
    assert "latency_ms" in result.normalized_fields


def test_normalized_envelope_is_pydantic_model():
    """Test 9: NormalizedEnvelope is a Pydantic model with correct fields."""
    env = NormalizedEnvelope(
        answer="Hello",
        sources=[Source(url="https://x.com")],
        confidence=0.5,
        latency_ms=100,
        normalized_fields=["foo"],
    )
    assert env.answer == "Hello"
    assert env.confidence == 0.5
