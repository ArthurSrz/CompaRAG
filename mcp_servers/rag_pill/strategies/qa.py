"""QA task prompt — answer using only the retrieved context, optionally with citations."""

from mcp_servers.rag_pill.schemas import QAPill


def render(pill: QAPill, context: str, task: str, goal: str) -> str:
    cite = " Cite source chunks." if pill.cite_sources else ""
    instruction = f"Answer the question using ONLY the context.{cite}"
    query = f"{task} {goal}".strip()
    return (
        f"{instruction}\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {query}\n\n"
        f"Answer:"
    )
