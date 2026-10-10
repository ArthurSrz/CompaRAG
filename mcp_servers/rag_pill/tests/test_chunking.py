"""The shared chunker — offsets must be exact, because spans depend on them."""

from __future__ import annotations

import pytest

from mcp_servers.rag_pill.corpus.ephemeral import EphemeralCorpus
from mcp_servers.rag_pill.engines.chunking import chunk_corpus, chunk_document

TEXT = "".join(f"phrase numero {i}. " for i in range(20))


def test_every_chunk_slices_back_to_its_own_text() -> None:
    for chunk in chunk_document("d", TEXT, chunk_size=50, chunk_overlap=10):
        assert TEXT[chunk.char_start : chunk.char_end] == chunk.text


def test_windows_advance_by_size_minus_overlap() -> None:
    chunks = list(chunk_document("d", TEXT, chunk_size=50, chunk_overlap=10))
    starts = [c.char_start for c in chunks]
    assert starts[:3] == [0, 40, 80]


def test_the_whole_document_is_covered() -> None:
    chunks = list(chunk_document("d", TEXT, chunk_size=50, chunk_overlap=10))
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(TEXT)


def test_overlap_zero_partitions_without_gaps() -> None:
    chunks = list(chunk_document("d", TEXT, chunk_size=30, chunk_overlap=0))
    assert "".join(c.text for c in chunks) == TEXT


def test_blank_windows_are_dropped() -> None:
    assert list(chunk_document("d", "   \n  \t ", chunk_size=4, chunk_overlap=0)) == []


def test_empty_document_yields_nothing() -> None:
    assert list(chunk_document("d", "", chunk_size=10, chunk_overlap=0)) == []


def test_overlap_at_or_above_size_is_refused() -> None:
    """Silently looping forever is the failure this prevents."""
    with pytest.raises(ValueError, match="never advances"):
        list(chunk_document("d", TEXT, chunk_size=10, chunk_overlap=10))


def test_chunk_corpus_tags_each_chunk_with_its_document() -> None:
    corpus = EphemeralCorpus(TEXT)
    doc_id = next(iter(corpus.iter_documents())).id
    chunks = chunk_corpus(corpus, chunk_size=60, chunk_overlap=0)
    assert chunks
    assert {c.doc_id for c in chunks} == {doc_id}
