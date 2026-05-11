"""EngineResult + RetrievedSpan — comparable retrieval-output unit.

Replaces the bare `str` return from engine.execute(). Wave 3 introduces these
as the typed output of a NEW method `execute_with_spans()`; the legacy
`execute() -> str` stays additive (calls execute_with_spans internally and
returns just .answer) so existing callers (retry.py, server.py) keep working
during the migration.

The interval `[char_start, char_end)` is the comparable unit the
RetrievalJudge uses (plan 13-05) to compute Recall@K / MRR / NDCG against
EvaluationQuery.expected_spans (plan 13-04).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievedSpan:
    """One chunk an engine retrieved, projected onto a corpus-source-relative
    [char_start, char_end) interval."""

    source_doc_id: str
    char_start: int
    char_end: int
    text: str
    score: float | None
    rank: int


@dataclass(frozen=True)
class EngineResult:
    """Engine's typed output. The legacy `execute() -> str` returns this
    object's `.answer`; the new `execute_with_spans()` returns the full
    struct including retrieved_spans + latencies."""

    answer: str
    retrieved_spans: tuple[RetrievedSpan, ...]
    retrieval_latency_ms: int
    generation_latency_ms: int
    unlocated_span_count: int = 0
