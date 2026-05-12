"""RetrievalJudge Protocol + JudgementScore dataclass.

Single seam — v1 has one adapter (GroundTruthJudge). Future HumanJudge /
LLMJudge plug in here without disturbing the dispatcher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


# Inlined to keep backend image free of mcp_servers/ — rag_pill is a sibling
# Railway service with its own Dockerfile. Definitions MUST stay structurally
# identical to mcp_servers.rag_pill.corpus.ExpectedSpan and
# mcp_servers.rag_pill.engines.result.RetrievedSpan; if either grows fields,
# mirror them here. The judge compares `[char_start, char_end)` intervals
# scoped to source_doc_id — that's the contract Wave 6 wire-format relies on.
@dataclass(frozen=True)
class ExpectedSpan:
    source_doc_id: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class RetrievedSpan:
    source_doc_id: str
    char_start: int
    char_end: int
    text: str
    score: float | None
    rank: int


@dataclass(frozen=True)
class JudgementScore:
    """Per-side retrieval quality score. Persisted as JSONB on
    tool_votes.judgement_{a,b} (migration 006)."""

    contains_gold: bool
    recall_at_k: dict[int, float]
    mrr: float
    ndcg_at_10: float
    hits: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "contains_gold": self.contains_gold,
            "recall_at_k": {str(k): v for k, v in self.recall_at_k.items()},
            "mrr": self.mrr,
            "ndcg_at_10": self.ndcg_at_10,
            "hits": self.hits,
        }


class RetrievalJudge(Protocol):
    id: str

    def score(
        self,
        retrieved: list[RetrievedSpan],
        expected: list[ExpectedSpan],
    ) -> JudgementScore:
        ...
