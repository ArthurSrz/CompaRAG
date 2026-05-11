"""HaystackCorpus seam — base contracts, FixedCorpus, EphemeralCorpus.

Per Phase 13 (needle-in-haystack arena), engines accept a HaystackCorpus
per-call rather than reaching into a hardcoded CORPUS_DIR. Two adapters
earn the seam: FixedCorpus (curated benchmark) and EphemeralCorpus
(user upload, sandbox).

Tests below drive the module's contract (slices 2.1-2.8 of the TDD plan).
"""

from mcp_servers.rag_pill.corpus.base import (
    CorpusDocument,
    compute_version_hash,
)


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
