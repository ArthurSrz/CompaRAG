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
    EvaluationQuery,
    ExpectedSpan,
    compute_version_hash,
)
from mcp_servers.rag_pill.corpus.ephemeral import EphemeralCorpus
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


def test_fixed_corpus_has_ground_truth_false_without_queries_yaml(tmp_path: Path) -> None:
    """A directory of .md files with no evaluation/queries.yaml is not a
    benchmark corpus — has_ground_truth must surface that distinction so
    the judge knows whether automated scoring is even possible."""
    (tmp_path / "only.md").write_text("hello")
    corpus = FixedCorpus(tmp_path)
    assert corpus.has_ground_truth is False


def test_fixed_corpus_loads_evaluation_queries(tmp_path: Path) -> None:
    """When evaluation/queries.yaml is present, list_evaluation_queries()
    returns parsed EvaluationQuery entries with expected_spans intact."""
    (tmp_path / "geography_fr.md").write_text("Paris est la capitale de la France.")
    (tmp_path / "evaluation").mkdir()
    (tmp_path / "evaluation" / "queries.yaml").write_text(
        """\
- id: q01_capital_france
  query_text: "Quelle est la capitale de la France ?"
  goal_text: "Réponse précise."
  expected_spans:
    - source_doc_id: "geography_fr.md"
      char_start: 0
      char_end: 35
  notes: "Easy needle."
"""
    )

    corpus = FixedCorpus(tmp_path)
    assert corpus.has_ground_truth is True
    queries = corpus.list_evaluation_queries()

    assert len(queries) == 1
    q = queries[0]
    assert isinstance(q, EvaluationQuery)
    assert q.id == "q01_capital_france"
    assert q.query_text.startswith("Quelle")
    assert q.goal_text == "Réponse précise."
    assert q.notes == "Easy needle."
    assert len(q.expected_spans) == 1
    span = q.expected_spans[0]
    assert isinstance(span, ExpectedSpan)
    assert span.source_doc_id == "geography_fr.md"
    assert (span.char_start, span.char_end) == (0, 35)


def test_fixed_corpus_raises_on_malformed_queries_yaml(tmp_path: Path) -> None:
    """A top-level dict (instead of list) in queries.yaml is a hand-edit
    error worth catching loudly — silently returning [] would mask the bug."""
    (tmp_path / "a.md").write_text("x")
    (tmp_path / "evaluation").mkdir()
    (tmp_path / "evaluation" / "queries.yaml").write_text("not_a_list: {id: q1}")

    corpus = FixedCorpus(tmp_path)
    with pytest.raises(ValueError, match="list"):
        corpus.list_evaluation_queries()


def test_ephemeral_corpus_empty_text_raises() -> None:
    """Sandbox mode requires non-empty content. Whitespace-only counts as
    empty — otherwise a user submitting only spaces would produce a corpus
    with one zero-information document and confuse downstream retrieval."""
    with pytest.raises(ValueError):
        EphemeralCorpus("")
    with pytest.raises(ValueError):
        EphemeralCorpus("   \n\t  ")


def test_ephemeral_corpus_upload_id_deterministic() -> None:
    """Same text -> same upload id (cache hit); different text -> different.
    Determinism keeps cached engine indices reusable across identical uploads."""
    a1 = EphemeralCorpus("Paris is the capital of France.")
    a2 = EphemeralCorpus("Paris is the capital of France.")
    b = EphemeralCorpus("Berlin is the capital of Germany.")

    a1_id = next(iter(a1.iter_documents())).id
    a2_id = next(iter(a2.iter_documents())).id
    b_id = next(iter(b.iter_documents())).id

    assert a1_id == a2_id
    assert a1_id != b_id
    assert a1_id.startswith("upload-")
    assert a1.has_ground_truth is False
