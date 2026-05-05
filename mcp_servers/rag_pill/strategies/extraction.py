"""Extraction task prompt — render JSON-shaped extraction request.

No engine declares `extraction` in SUPPORTS yet, so this is wired but unused
until a backend (LangChain `with_structured_output`, LlamaIndex `Pydantic
program`, etc.) is bound. Defining the prompt now keeps the strategies module
exhaustive over the schema's task_type literal — Pydantic will catch a future
fourth task_type at config-load time, this module catches it at render time.
"""

import json

from mcp_servers.rag_pill.schemas import ExtractionPill


def render(pill: ExtractionPill, context: str, task: str, goal: str) -> str:
    schema_str = json.dumps(pill.output_schema, indent=2, ensure_ascii=False)
    query = f"{task} {goal}".strip()
    return (
        f"Extract data from the context matching this JSON schema:\n{schema_str}\n\n"
        f"Return ONLY valid JSON, no prose.\n\n"
        f"Context:\n{context}\n\n"
        f"Goal: {query}\n\n"
        f"JSON:"
    )
