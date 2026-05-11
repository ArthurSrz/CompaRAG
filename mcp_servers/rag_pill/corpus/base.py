"""HaystackCorpus base contracts — CorpusDocument + version-hash helper.

The version hash invalidates cached engine indices when the corpus
content changes. Stability across input order is critical: corpus
loaders may yield documents in different orders across runs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class CorpusDocument:
    """One source document inside a HaystackCorpus."""

    id: str
    text: str
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ExpectedSpan:
    """One [char_start, char_end) interval where an answer is known to live."""

    source_doc_id: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class EvaluationQuery:
    """A query whose ground-truth answer spans are known."""

    id: str
    query_text: str
    goal_text: str
    expected_spans: tuple[ExpectedSpan, ...]
    notes: str | None = None


def compute_version_hash(documents: Iterable[CorpusDocument]) -> str:
    """sha256 over sorted(doc_id, text) — stable across input order."""
    hasher = hashlib.sha256()
    for doc in sorted(documents, key=lambda d: d.id):
        hasher.update(doc.id.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(doc.text.encode("utf-8"))
        hasher.update(b"\x01")
    return hasher.hexdigest()
