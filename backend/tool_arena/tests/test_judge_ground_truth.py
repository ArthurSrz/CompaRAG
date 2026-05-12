"""GroundTruthJudge — Recall@K / MRR / NDCG@10 over interval overlap.

Pure-function tests with hand-computed expectations. No mocks, no fixtures.
The judge is the most numerically sensitive module in Phase 13; each metric
has its own slice with a deterministic expectation.
"""

from backend.tool_arena.judge.base import ExpectedSpan
from backend.tool_arena.judge.base import RetrievedSpan

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


def test_perfect_hit_at_rank_zero_gives_mrr_one() -> None:
    """Slice 5.4 — single retrieved overlaps single expected -> MRR=1.0,
    Recall@1=1.0, contains_gold=True."""
    score = GroundTruthJudge().score(
        retrieved=[_span("a.md", 1245, 1389, rank=0, score=0.95)],
        expected=[ExpectedSpan("a.md", 1245, 1389)],
    )
    assert score.contains_gold is True
    assert score.mrr == 1.0
    assert score.recall_at_k[1] == 1.0
    assert score.hits == [{"rank": 0, "expected_span_idx": 0}]


def test_hit_at_rank_two_gives_mrr_one_third() -> None:
    """Slice 5.5 — first hit at rank=2 -> MRR=1/(1+2)=1/3.
    Recall@1=0 (no hit yet); Recall@3=1.0 (top-3 contains the hit)."""
    score = GroundTruthJudge().score(
        retrieved=[
            _span("a.md", 0, 50, rank=0),    # miss
            _span("a.md", 60, 80, rank=1),   # miss
            _span("a.md", 1245, 1389, rank=2),  # hit
        ],
        expected=[ExpectedSpan("a.md", 1245, 1389)],
    )
    assert abs(score.mrr - 1.0 / 3) < 1e-9
    assert score.recall_at_k[1] == 0.0
    assert score.recall_at_k[3] == 1.0


def test_recall_at_k_grows_monotonically_with_two_expected() -> None:
    """Slice 5.6 — 2 expected, hits at ranks 0 and 4. Recall@1=0.5 (1/2),
    Recall@3=0.5 (still just 1 unique hit in top-3), Recall@5=1.0 (both
    hits in top-5). Monotonic."""
    score = GroundTruthJudge().score(
        retrieved=[
            _span("a.md", 0, 10, rank=0),     # hits expected[0]
            _span("a.md", 100, 110, rank=1),  # miss
            _span("a.md", 200, 210, rank=2),  # miss
            _span("a.md", 300, 310, rank=3),  # miss
            _span("a.md", 500, 510, rank=4),  # hits expected[1]
        ],
        expected=[ExpectedSpan("a.md", 5, 12), ExpectedSpan("a.md", 505, 515)],
    )
    assert score.recall_at_k[1] == 0.5
    assert score.recall_at_k[3] == 0.5
    assert score.recall_at_k[5] == 1.0
    assert score.recall_at_k[10] == 1.0


def test_overlap_definition_is_strict() -> None:
    """Slice 5.7 — touching boundaries don't overlap. Retrieved [5, 10) and
    expected [10, 15) are disjoint; no hit. Catches the off-by-one bug
    where `max(...) <= min(...)` would inflate Recall@K artificially."""
    score = GroundTruthJudge().score(
        retrieved=[_span("a.md", 5, 10, rank=0)],
        expected=[ExpectedSpan("a.md", 10, 15)],
    )
    assert score.contains_gold is False
    assert score.mrr == 0.0


def test_different_source_doc_no_match() -> None:
    """Slice 5.8 — same char ranges in different files don't overlap.
    `intro.md[0:100]` and `outro.md[0:100]` share zero territory."""
    score = GroundTruthJudge().score(
        retrieved=[_span("intro.md", 0, 100, rank=0)],
        expected=[ExpectedSpan("outro.md", 0, 100)],
    )
    assert score.contains_gold is False
    assert score.recall_at_k[10] == 0.0


def test_ndcg_log2_decay_known_value() -> None:
    """Slice 5.9 — three expected; hits at ranks 0, 2, 5. Hand-computed:
        DCG = 1/log2(2) + 1/log2(4) + 1/log2(7)
            = 1.0 + 0.5 + 0.3562...
            ≈ 1.8562
        IDCG (3 hits at ranks 0,1,2) = 1.0 + 0.6309... + 0.5
                                     ≈ 2.1309
        NDCG ≈ 1.8562 / 2.1309 ≈ 0.8711
    Pins the log2 base and the rank-shift (+i, not +i+1)."""
    import math as _m
    dcg = 1.0 / _m.log2(2) + 1.0 / _m.log2(4) + 1.0 / _m.log2(7)
    idcg = sum(1.0 / _m.log2(2 + i) for i in range(3))
    expected_ndcg = dcg / idcg

    score = GroundTruthJudge().score(
        retrieved=[
            _span("a.md", 0, 10, rank=0),     # hits expected[0]
            _span("a.md", 50, 60, rank=1),    # miss
            _span("a.md", 100, 110, rank=2),  # hits expected[1]
            _span("a.md", 200, 210, rank=3),  # miss
            _span("a.md", 300, 310, rank=4),  # miss
            _span("a.md", 400, 410, rank=5),  # hits expected[2]
        ],
        expected=[
            ExpectedSpan("a.md", 5, 12),
            ExpectedSpan("a.md", 105, 115),
            ExpectedSpan("a.md", 405, 415),
        ],
    )
    assert abs(score.ndcg_at_10 - expected_ndcg) < 1e-9
