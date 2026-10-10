"""The benchmark corpus and its ground truth.

Character offsets are the whole contract here: the judge scores a retrieval
by interval overlap, so an offset that drifts by one character does not
raise — it silently scores against the wrong text and every metric becomes
fiction. These tests exist to make that drift loud.

The generator (scripts/build_eval_queries.py) resolves offsets from text
anchors, so the guard is cheap: re-resolve and compare.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_servers.rag_pill.corpus.fixed import FixedCorpus

CORPUS_DIR = Path(__file__).resolve().parents[3] / "mcp_servers" / "corpus"


@pytest.fixture(scope="module")
def corpus() -> FixedCorpus:
    if not any(CORPUS_DIR.glob("*.md")):
        pytest.skip(f"{CORPUS_DIR} holds no corpus documents")
    return FixedCorpus(CORPUS_DIR)


def test_corpus_has_ground_truth(corpus) -> None:
    assert corpus.has_ground_truth, "evaluation/queries.yaml is missing"
    assert corpus.list_evaluation_queries(), "the catalogue is empty"


def test_every_expected_span_points_at_real_text(corpus) -> None:
    """The guard that matters. A span must land inside its document and
    cover non-whitespace — otherwise the judge scores against nothing."""
    documents = {d.id: d.text for d in corpus.iter_documents()}

    for query in corpus.list_evaluation_queries():
        assert query.expected_spans, f"{query.id} has no expected span"
        for span in query.expected_spans:
            assert span.source_doc_id in documents, (
                f"{query.id} points at an unknown document "
                f"{span.source_doc_id!r} (corpus holds {sorted(documents)})"
            )
            text = documents[span.source_doc_id]
            assert 0 <= span.char_start < span.char_end <= len(text), (
                f"{query.id} span [{span.char_start}, {span.char_end}) is out "
                f"of bounds for {span.source_doc_id} ({len(text)} chars)"
            )
            assert text[span.char_start : span.char_end].strip(), (
                f"{query.id} span covers only whitespace in {span.source_doc_id}"
            )


def test_generated_catalogue_is_in_sync_with_the_corpus() -> None:
    """Running the generator must be a no-op. If it is not, a corpus file was
    edited without regenerating, and every offset below the edit has moved."""
    import subprocess
    import sys

    root = CORPUS_DIR.parent.parent
    result = subprocess.run(
        [sys.executable, "scripts/build_eval_queries.py", "--check"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "queries.yaml is stale — run scripts/build_eval_queries.py\n"
        f"{result.stderr}"
    )


def test_the_catalogue_keeps_multi_hop_questions(corpus) -> None:
    """The point of this corpus. A question whose answer needs two passages
    is the only kind that measures whether a retriever can chain — and it is
    the first thing a well-meaning edit would flatten."""
    multi_hop = [q for q in corpus.list_evaluation_queries() if len(q.expected_spans) > 1]
    assert multi_hop, "no multi-hop question left in the catalogue"

    cross_document = [
        q for q in multi_hop if len({s.source_doc_id for s in q.expected_spans}) > 1
    ]
    assert cross_document, (
        "no multi-hop question spans two documents — single-document hops can "
        "be satisfied by one lucky chunk"
    )


def test_the_distractor_manual_is_present(corpus) -> None:
    """Le Breuil exists only to be wrong convincingly. Without it, every
    question has exactly one plausible document and retrieval is trivial."""
    ids = {d.id for d in corpus.iter_documents()}
    assert "manuel_station_vaux.md" in ids
    assert "manuel_station_breuil.md" in ids, (
        "the near-identical distractor manual is gone — the benchmark no "
        "longer tests discrimination"
    )
