"""Server-side evaluation query metadata loader.

Reads the same `corpus/evaluation/queries.yaml` that rag_pill's FixedCorpus
reads but exposes ONLY the metadata (id, query_text, goal_text) the router
needs to substitute task/goal text in benchmark mode. expected_spans stay in
rag_pill — the judge (plan 13-05) runs there; the backend never touches
ground truth directly.

The two loaders MUST agree on the corpus version (enforced at deploy time
by shipping the same YAML to both surfaces).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import yaml

from mcp_servers.rag_pill.corpus import ExpectedSpan


@dataclass(frozen=True)
class EvaluationQueryMeta:
    id: str
    query_text: str
    goal_text: str
    expected_spans: tuple[ExpectedSpan, ...] = field(default_factory=tuple)


class EvaluationCatalog:
    """Lazy YAML reader keyed by query id. Path may not exist; lookups
    just return empty/None until the file appears (lets the backend start
    even before the corpus is mounted)."""

    def __init__(self, queries_path: Path) -> None:
        self._path = Path(queries_path)

    @cached_property
    def _by_id(self) -> dict[str, EvaluationQueryMeta]:
        if not self._path.exists():
            return {}
        data = yaml.safe_load(self._path.read_text())
        if not isinstance(data, list):
            raise ValueError(
                f"{self._path} must be a top-level list of query entries"
            )
        return {
            entry["id"]: EvaluationQueryMeta(
                id=entry["id"],
                query_text=entry["query_text"],
                goal_text=entry.get("goal_text", ""),
                expected_spans=tuple(
                    ExpectedSpan(
                        source_doc_id=s["source_doc_id"],
                        char_start=int(s["char_start"]),
                        char_end=int(s["char_end"]),
                    )
                    for s in entry.get("expected_spans", [])
                ),
            )
            for entry in data
        }

    def get(self, query_id: str) -> EvaluationQueryMeta | None:
        return self._by_id.get(query_id)

    def list_ids(self) -> list[str]:
        return list(self._by_id.keys())
