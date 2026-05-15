"""
BUT : produire un JudgeVerdict — un score automatique de la qualité d'une
réponse — en comparant les passages que le RAGTool a retrouvés aux passages
attendus pour cette Question. Trois métriques : Recall@K, MRR, NDCG@K.

Future home (cf. knowledge-graph/code-ontology.yaml) :
    backend/tool_arena/judge_verdict/score_against_ground_truth.py

GroundTruthJudge — score retrieval against curated ExpectedSpan list.

A retrieved span counts as a hit on an expected span iff their character
intervals overlap (within the same source_doc_id). Each retrieved span at
most one expected span (greedy first-match by index).

Recall@K = |unique expected spans hit by top-K retrieved| / |total expected|
MRR     = 1/(1+rank) of first hit, else 0
NDCG@K  = sum_i (rel_i / log2(2+i)) / IDCG, where rel_i = 1 if hit else 0
"""

from __future__ import annotations

import math

from backend.tool_arena.judge_verdict.base import (
    ExpectedSpan,
    JudgementScore,
    RetrievedSpan,
)


_K_VALUES: tuple[int, ...] = (1, 3, 5, 10)


def _overlaps(r: RetrievedSpan, e: ExpectedSpan) -> bool:
    """Strict interval overlap inside the same source doc. Touching
    boundaries do NOT count — `[5, 10)` and `[10, 15)` are disjoint."""
    return (
        r.source_doc_id == e.source_doc_id
        and max(r.char_start, e.char_start) < min(r.char_end, e.char_end)
    )


def _hit_indices(
    retrieved: list[RetrievedSpan],
    expected: list[ExpectedSpan],
) -> list[int | None]:
    """For each retrieved span (rank order), the index of the expected span
    it overlaps, or None. Greedy first-match — a retrieved span hits at most
    one expected span (the first index in expected that overlaps)."""
    return [
        next((i for i, e in enumerate(expected) if _overlaps(r, e)), None)
        for r in retrieved
    ]


def _recall_at(hits: list[int | None], k: int, total_expected: int) -> float:
    if total_expected == 0:
        return 0.0
    unique = {h for h in hits[:k] if h is not None}
    return len(unique) / total_expected


def _mrr(hits: list[int | None]) -> float:
    for rank, h in enumerate(hits):
        if h is not None:
            return 1.0 / (1.0 + rank)
    return 0.0


def _ndcg_at(hits: list[int | None], k: int, total_expected: int) -> float:
    if total_expected == 0:
        return 0.0
    dcg = sum(
        (1.0 / math.log2(2 + i))
        for i, h in enumerate(hits[:k])
        if h is not None
    )
    ideal_count = min(k, total_expected)
    idcg = sum(1.0 / math.log2(2 + i) for i in range(ideal_count))
    return dcg / idcg if idcg > 0 else 0.0


class GroundTruthJudge:
    id = "ground_truth"

    def score(
        self,
        retrieved: list[RetrievedSpan],
        expected: list[ExpectedSpan],
    ) -> JudgementScore:
        sorted_retrieved = sorted(retrieved, key=lambda r: r.rank)
        hits = _hit_indices(sorted_retrieved, expected)
        return JudgementScore(
            contains_gold=any(h is not None for h in hits),
            recall_at_k={k: _recall_at(hits, k, len(expected)) for k in _K_VALUES},
            mrr=_mrr(hits),
            ndcg_at_10=_ndcg_at(hits, 10, len(expected)),
            hits=[
                {"rank": rank, "expected_span_idx": h}
                for rank, h in enumerate(hits)
                if h is not None
            ],
        )
