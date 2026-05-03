"""RAGEngine Protocol — the contract every engine adapter implements."""

from typing import Protocol, runtime_checkable

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
        document_content: str,
    ) -> str:
        """Run the pill against the document and return the synthesized answer."""
        ...
