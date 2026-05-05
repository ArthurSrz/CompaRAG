"""Summary task prompt — compresses the retrieved context to ~ratio of source."""

from mcp_servers.rag_pill.schemas import SummaryPill


def render(pill: SummaryPill, context: str, task: str, goal: str) -> str:
    pct = int(pill.compression_ratio * 100)
    instruction = (
        f"Summarize the context as {pill.style}, "
        f"compressing to ~{pct}% of source length."
    )
    query = f"{task} {goal}".strip()
    return (
        f"{instruction}\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {query}\n\n"
        f"Answer:"
    )
