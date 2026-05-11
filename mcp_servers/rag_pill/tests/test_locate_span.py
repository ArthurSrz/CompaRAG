"""locate_span() — projects native engine chunks onto corpus char intervals.

Engines retrieve chunks (text strings); the helper finds where each chunk
lives in the source document and returns a RetrievedSpan with [char_start,
char_end). Failure modes (chunk not found in source) return None so the
caller can drop the span and increment unlocated_span_count.

Strategy: post-hoc `source.find(chunk_text)`. Cheap, deterministic, doesn't
require engines to preserve offsets through their internal splitters.
"""

from mcp_servers.rag_pill.corpus.ephemeral import EphemeralCorpus
from mcp_servers.rag_pill.engines.base import locate_span


def test_locate_span_returns_offsets_for_present_text() -> None:
    """Happy path: chunk text exists at a known position in the source."""
    corpus = EphemeralCorpus("Hello world. This is a test. Goodbye.")
    doc_id = next(iter(corpus.iter_documents())).id

    span = locate_span(corpus, doc_id, "This is a test.", score=0.8, rank=0)

    assert span is not None
    assert span.source_doc_id == doc_id
    assert span.char_start == 13
    assert span.char_end == 28
    assert span.text == "This is a test."
    assert span.score == 0.8
    assert span.rank == 0


def test_locate_span_returns_none_for_missing_text() -> None:
    """Chunk text absent from the source -> None. Caller increments
    EngineResult.unlocated_span_count and drops the span."""
    corpus = EphemeralCorpus("Hello world.")
    doc_id = next(iter(corpus.iter_documents())).id

    assert locate_span(corpus, doc_id, "not present", score=0.1, rank=1) is None


def test_locate_span_returns_none_for_unknown_doc_id() -> None:
    """source_doc_id not in corpus -> None. Engines may produce stale doc
    ids if a cache survives across corpus version changes."""
    corpus = EphemeralCorpus("Hello world.")

    assert locate_span(corpus, "unknown.md", "Hello", score=None, rank=0) is None


def test_locate_span_first_occurrence_when_text_repeats() -> None:
    """str.find() semantics: first occurrence wins. The judge is interval-
    overlap, so a chunk that legitimately matches multiple positions only
    counts once (its first-occurrence interval) — no Recall@K inflation."""
    corpus = EphemeralCorpus("abc abc abc")
    doc_id = next(iter(corpus.iter_documents())).id

    span = locate_span(corpus, doc_id, "abc", score=None, rank=0)
    assert span is not None
    assert (span.char_start, span.char_end) == (0, 3)
