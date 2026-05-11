"""HaystackCorpus seam — base contracts, FixedCorpus, EphemeralCorpus.

Per Phase 13 (needle-in-haystack arena), engines accept a HaystackCorpus
per-call rather than reaching into a hardcoded CORPUS_DIR. Two adapters
earn the seam: FixedCorpus (curated benchmark) and EphemeralCorpus
(user upload, sandbox).

Tests below drive the module's contract (slices 2.1-2.8 of the TDD plan).
"""

import dataclasses
from pathlib import Path

import pytest

from mcp_servers.rag_pill.corpus.base import (
    CorpusDocument,
    compute_version_hash,
)
from mcp_servers.rag_pill.corpus.fixed import FixedCorpus


def test_corpus_document_is_frozen() -> None:
    """CorpusDocument must be immutable — engines pass it through caches
    and dicts; mutation would silently corrupt cache keys."""
    d = CorpusDocument(id="a.md", text="hello")
    assert dataclasses.is_dataclass(d)
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.text = "tampered"  # type: ignore[misc]


def test_compute_version_hash_stable_across_input_order() -> None:
    """Hash must be deterministic regardless of input ordering — otherwise
    a corpus shuffled at load time would invalidate every cached index."""
    d1 = CorpusDocument(id="a.md", text="hello")
    d2 = CorpusDocument(id="b.md", text="world")
    d3 = CorpusDocument(id="c.md", text="!")

    h_forward = compute_version_hash([d1, d2, d3])
    h_reverse = compute_version_hash([d3, d2, d1])
    h_jumbled = compute_version_hash([d2, d3, d1])

    assert h_forward == h_reverse == h_jumbled
    assert len(h_forward) == 64  # sha256 hex


def test_fixed_corpus_iter_returns_md_files_sorted(tmp_path: Path) -> None:
    """Engines depend on a stable iteration order so cache keys stay stable
    across process restarts. Iteration must sort by filename."""
    (tmp_path / "c.md").write_text("# C\n\nthird.")
    (tmp_path / "a.md").write_text("# A\n\nfirst.")
    (tmp_path / "b.md").write_text("# B\n\nsecond.")

    corpus = FixedCorpus(tmp_path)
    ids = [doc.id for doc in corpus.iter_documents()]

    assert ids == ["a.md", "b.md", "c.md"]
