"""RetrievalJudge Protocol + JudgementScore dataclass.

Single seam — v1 has one adapter (GroundTruthJudge). Future HumanJudge /
LLMJudge plug in here without disturbing the dispatcher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from mcp_servers.rag_pill.corpus import ExpectedSpan
from mcp_servers.rag_pill.engines.result import RetrievedSpan


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
