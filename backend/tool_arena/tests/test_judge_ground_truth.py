"""GroundTruthJudge — Recall@K / MRR / NDCG@10 over interval overlap.

Pure-function tests with hand-computed expectations. No mocks, no fixtures.
The judge is the most numerically sensitive module in Phase 13; each metric
has its own slice with a deterministic expectation.
"""

from mcp_servers.rag_pill.corpus import ExpectedSpan
from mcp_servers.rag_pill.engines.result import RetrievedSpan

from backend.tool_arena.judge.base import JudgementScore
from backend.tool_arena.judge.ground_truth import GroundTruthJudge


def _span(doc: str, start: int, end: int, *, rank: int, score: float = 0.0) -> RetrievedSpan:
    """Test helper — RetrievedSpan factory."""
    return RetrievedSpan(
        source_doc_id=doc,
        char_start=start,
        char_end=end,
        text=f"chunk-{rank}",
        score=score,
        rank=rank,
    )


def test_no_retrieved_spans_returns_zero_scores() -> None:
    """Slice 5.2 — empty retrieved list yields all-zero score (no hit)."""
    score = GroundTruthJudge().score(retrieved=[], expected=[ExpectedSpan("a.md", 0, 10)])
    assert isinstance(score, JudgementScore)
    assert score.contains_gold is False
    assert score.mrr == 0.0
    assert score.recall_at_k == {1: 0.0, 3: 0.0, 5: 0.0, 10: 0.0}
    assert score.ndcg_at_10 == 0.0
    assert score.hits == []


def test_no_expected_spans_returns_zero_recall() -> None:
    """Slice 5.3 — empty expected list means there's nothing to recall.
    Recall denominator is 0 by definition; judge returns 0.0 (not NaN)."""
    score = GroundTruthJudge().score(
        retrieved=[_span("a.md", 0, 10, rank=0)],
        expected=[],
    )
    assert score.contains_gold is False
    assert score.mrr == 0.0
    assert all(v == 0.0 for v in score.recall_at_k.values())
