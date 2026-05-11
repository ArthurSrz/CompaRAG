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
