"""FixedCorpus — reads *.md from a directory; benchmark-mode haystack."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Iterable

from mcp_servers.rag_pill.corpus.base import CorpusDocument


class FixedCorpus:
    id = "fixed"

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        if not self._root.exists():
            raise FileNotFoundError(f"FixedCorpus root does not exist: {self._root}")

    @cached_property
    def _docs(self) -> list[CorpusDocument]:
        return [
            CorpusDocument(id=path.name, text=path.read_text())
            for path in sorted(self._root.glob("*.md"))
        ]

    def iter_documents(self) -> Iterable[CorpusDocument]:
        return iter(self._docs)
