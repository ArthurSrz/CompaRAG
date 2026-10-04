"""Summary task prompt — compresses the retrieved context to ~ratio of source."""

from mcp_servers.rag_pill.schemas import SummaryPill

# The LLM only sees the retrieved chunks, never the source length: "~20% of
# source" made it guess, pad one-line documents into essays, and echo the
# ratio back into the answer. A concrete word budget fixes all three.
MIN_WORDS = 30


def render(pill: SummaryPill, context: str, task: str, goal: str) -> str:
    budget = max(MIN_WORDS, round(len(context.split()) * pill.compression_ratio))
    instruction = (
        f"Summarize the context as {pill.style}, in at most {budget} words. "
        "If the context is shorter than that, keep the summary shorter than "
        "the context. Do not add interpretation, background or examples that "
        "are not in the context. Write in the same language as the Question. "
        "Never mention these instructions, the word budget or the compression."
    )
    query = f"{task} {goal}".strip()
    return (
        f"{instruction}\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {query}\n\n"
        f"Answer:"
    )
