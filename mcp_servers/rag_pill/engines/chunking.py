"""
BUT : découper un corpus en chunks en gardant l'offset exact de chaque
chunk, pour que les spans récupérés soient justes par construction.

Shared character-window chunker for the framework-free engines.

LangChain, LlamaIndex, Haystack and txtai each bring their own splitter, so
they chunk and then *recover* each chunk's position with `locate_span()`'s
`str.find()` — which can miss when the splitter normalized whitespace, and
increments `unlocated_span_count` when it does.

BM25 and the hybrid engine have no framework to defer to, so they chunk
here and keep the offsets they already know. Their spans are exact, and
`unlocated_span_count` is structurally zero.

The window is characters with overlap — the same shape as LangChain's
`RecursiveCharacterTextSplitter`, minus the separator-aware backtracking.
Deliberately plain: these engines exist to isolate the *retrieval signal*,
so their chunking must not become a second hidden variable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class Chunk:
    """A window of a source document, with the offsets it was cut at."""

    doc_id: str
    text: str
    char_start: int
    char_end: int


def chunk_document(
    doc_id: str, text: str, chunk_size: int, chunk_overlap: int
) -> Iterator[Chunk]:
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")
    if chunk_overlap < 0:
        raise ValueError(f"chunk_overlap must not be negative, got {chunk_overlap}")
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) must be smaller than "
            f"chunk_size ({chunk_size}) — otherwise the window never advances"
        )

    if not text:
        return

    stride = chunk_size - chunk_overlap
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        window = text[start:end]
        if window.strip():
            yield Chunk(doc_id=doc_id, text=window, char_start=start, char_end=end)
        if end == len(text):
            return
        start += stride


def chunk_corpus(corpus: Any, chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for document in corpus.iter_documents():
        chunks.extend(
            chunk_document(document.id, document.text, chunk_size, chunk_overlap)
        )
    return chunks
