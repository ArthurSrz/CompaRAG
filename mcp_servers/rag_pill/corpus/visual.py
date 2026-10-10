"""
BUT : donner aux moteurs visuels (ColPali) les *pages rendues en image*,
sans casser le contrat CorpusDocument que consomment les moteurs texte.

VisualCorpus — PDF pages as (image, text, char-span) triples.

Every other corpus in this package yields text only, because every other
engine embeds text. ColPali embeds the page *image*, so it needs pixels —
but the arena's judge scores retrieval as `[char_start, char_end)` intervals
over the source document (see `corpus/base.ExpectedSpan`). A corpus that
handed out images alone would make its engine unscoreable, and an
unscoreable engine cannot share a leaderboard with the text engines.

VisualCorpus therefore carries both halves: every page knows its PNG bytes
AND where its extracted text lives inside the parent document's
concatenated text. A visual retriever ranks on pixels and reports spans on
characters, so Recall@K means exactly the same thing for ColPali as it does
for LangChain.

The text half also means text engines can read this corpus unchanged:
`iter_documents()` yields ordinary CorpusDocuments whose `.text` is the
page texts joined by PAGE_SEPARATOR. One corpus, both paradigms, same
ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Iterable

import yaml

from mcp_servers.rag_pill.corpus.base import (
    CorpusDocument,
    EvaluationQuery,
    ExpectedSpan,
    compute_version_hash,
)


def _import_pymupdf():
    """PyMuPDF ships as `pymupdf` (>=1.24) and `fitz` (legacy). Accept both."""
    try:
        import pymupdf  # noqa: PLC0415

        return pymupdf
    except ImportError:
        import fitz  # noqa: PLC0415

        return fitz


@dataclass(frozen=True)
class PageRef:
    """One PDF page: its text, its interval in the parent doc, its pixels.

    `char_start`/`char_end` index into the *document* text produced by
    VisualCorpus — i.e. into `get_document(doc_id).text` — so a RetrievedSpan
    built from a PageRef needs no `locate_span()` string search. The offsets
    are exact by construction rather than recovered by `str.find()`.
    """

    doc_id: str
    page_number: int  # 0-based
    text: str
    char_start: int
    char_end: int
    source_path: Path

    @property
    def page_id(self) -> str:
        return f"{self.doc_id}#p{self.page_number}"


class VisualCorpus:
    """Reads `*.pdf` from a directory. Pages are the retrieval unit."""

    id = "visual"

    # Joins page texts into the document text. Two newlines, so a page break
    # reads as a paragraph break to any text engine consuming this corpus.
    PAGE_SEPARATOR = "\n\n"

    def __init__(self, root: Path, dpi: int = 150) -> None:
        self._root = Path(root)
        if not self._root.exists():
            raise FileNotFoundError(f"VisualCorpus root does not exist: {self._root}")
        self._dpi = dpi
        self._queries_path: Path | None = self._root / "evaluation" / "queries.yaml"
        if not self._queries_path.exists():
            self._queries_path = None

    @property
    def dpi(self) -> int:
        return self._dpi

    @property
    def has_ground_truth(self) -> bool:
        return self._queries_path is not None

    @cached_property
    def _loaded(self) -> tuple[list[CorpusDocument], list[PageRef]]:
        pymupdf = _import_pymupdf()
        docs: list[CorpusDocument] = []
        pages: list[PageRef] = []

        for path in sorted(self._root.glob("*.pdf")):
            doc_id = path.name
            page_texts: list[str] = []
            offset = 0
            with pymupdf.open(path) as pdf:
                for page_number, page in enumerate(pdf):
                    text = page.get_text()
                    page_texts.append(text)
                    pages.append(
                        PageRef(
                            doc_id=doc_id,
                            page_number=page_number,
                            text=text,
                            char_start=offset,
                            char_end=offset + len(text),
                            source_path=path,
                        )
                    )
                    offset += len(text) + len(self.PAGE_SEPARATOR)
            docs.append(
                CorpusDocument(
                    id=doc_id,
                    text=self.PAGE_SEPARATOR.join(page_texts),
                    meta={"page_count": len(page_texts), "format": "pdf"},
                )
            )

        return docs, pages

    @property
    def _docs(self) -> list[CorpusDocument]:
        return self._loaded[0]

    def iter_documents(self) -> Iterable[CorpusDocument]:
        return iter(self._docs)

    def get_document(self, doc_id: str) -> CorpusDocument | None:
        for d in self._docs:
            if d.id == doc_id:
                return d
        return None

    def iter_pages(self) -> Iterable[PageRef]:
        return iter(self._loaded[1])

    @property
    def page_count(self) -> int:
        return len(self._loaded[1])

    def render_pages(self) -> list[tuple[PageRef, bytes]]:
        """Render every page to PNG bytes, opening each PDF exactly once.

        Rendering is deliberately NOT done in `_loaded`: text engines reading
        this corpus must not pay for pixels they will never embed.
        """
        pymupdf = _import_pymupdf()
        out: list[tuple[PageRef, bytes]] = []
        by_path: dict[Path, list[PageRef]] = {}
        for page in self.iter_pages():
            by_path.setdefault(page.source_path, []).append(page)

        for path, refs in by_path.items():
            with pymupdf.open(path) as pdf:
                for ref in refs:
                    pixmap = pdf[ref.page_number].get_pixmap(dpi=self._dpi)
                    out.append((ref, pixmap.tobytes("png")))
        return out

    @cached_property
    def version_hash(self) -> str:
        return compute_version_hash(self._docs)

    def list_evaluation_queries(self) -> list[EvaluationQuery]:
        if self._queries_path is None:
            return []
        data = yaml.safe_load(self._queries_path.read_text())
        if not isinstance(data, list):
            raise ValueError(
                f"{self._queries_path} must be a top-level list of query entries"
            )
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
