"""RAGEngine Protocol + shared span-projection helper."""

from typing import Any, Protocol, runtime_checkable

from mcp_servers.rag_pill.engines.result import RetrievedSpan
from mcp_servers.rag_pill.schemas import Pill


def locate_span(
    corpus: Any,
    source_doc_id: str,
    chunk_text: str,
    *,
    score: float | None,
    rank: int,
) -> RetrievedSpan | None:
    """Project a native engine chunk onto a corpus-relative RetrievedSpan.

    Strategy: read the source doc, find chunk_text via str.find(). First
    occurrence wins (rare collisions for >50-char chunks; judge is interval-
    overlap so repeats don't inflate Recall@K). Returns None if not found
    (engine normalized whitespace, splitter smoothed a boundary, etc.) —
    caller increments EngineResult.unlocated_span_count.
    """
    doc = corpus.get_document(source_doc_id) if hasattr(corpus, "get_document") else None
    if doc is None:
        return None
    start = doc.text.find(chunk_text)
    if start < 0:
        return None
    return RetrievedSpan(
        source_doc_id=source_doc_id,
        char_start=start,
        char_end=start + len(chunk_text),
        text=chunk_text,
        score=score,
        rank=rank,
    )


@runtime_checkable
class RAGEngine(Protocol):
    id: str
    SUPPORTS: set[str]  # task_type names this engine can execute

    async def execute(
        self,
        pill: Pill,
        task: str,
        goal: str,
        corpus: Any,
    ) -> str:
        """Run the pill against the corpus and return the synthesized answer.

        `corpus` is anything with `iter_documents() -> Iterable[CorpusDocument]`
        — typically `FixedCorpus` (benchmark) or `EphemeralCorpus` (sandbox).
        Slice 2.10 refactors each concrete engine to consume `corpus` directly
        instead of the legacy `document_content: str`.
        """
        ...
