"""RAGEngine Protocol — the contract every engine adapter implements."""

from typing import Any, Protocol, runtime_checkable

from mcp_servers.rag_pill.schemas import Pill


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
