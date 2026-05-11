"""FixedCorpus — reads *.md from a directory; benchmark-mode haystack."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Iterable

import yaml

from mcp_servers.rag_pill.corpus.base import (
    CorpusDocument,
    EvaluationQuery,
    ExpectedSpan,
)


class FixedCorpus:
    id = "fixed"

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        if not self._root.exists():
            raise FileNotFoundError(f"FixedCorpus root does not exist: {self._root}")
        self._queries_path: Path | None = self._root / "evaluation" / "queries.yaml"
        if not self._queries_path.exists():
            self._queries_path = None

    @property
    def has_ground_truth(self) -> bool:
        return self._queries_path is not None

    @cached_property
    def _docs(self) -> list[CorpusDocument]:
        return [
            CorpusDocument(id=path.name, text=path.read_text())
            for path in sorted(self._root.glob("*.md"))
        ]

    def iter_documents(self) -> Iterable[CorpusDocument]:
        return iter(self._docs)

    def list_evaluation_queries(self) -> list[EvaluationQuery]:
        if self._queries_path is None:
            return []
        data = yaml.safe_load(self._queries_path.read_text())
        return [
            EvaluationQuery(
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
                notes=entry.get("notes"),
            )
            for entry in data
        ]
