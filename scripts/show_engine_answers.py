"""Run each new engine end-to-end and print the answer for visual inspection.

Two scenarios per engine:
  A) Uploaded ZORBLIX doc → assert grounded answer mentions port 4242
  B) Bundled corpus, no upload → ask about Python asyncio

Reads OPENROUTER_API_KEY from .env (via the conftest's load_dotenv side effect
in the rag_pill package).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(override=False)

from mcp_servers.rag_pill.cache import IndexCache  # noqa: E402
from mcp_servers.rag_pill.engines import (  # noqa: E402
    ChromaBaselineEngine,
    HaystackEngine,
    TxtaiEngine,
)
from mcp_servers.rag_pill.providers import EmbeddingConfig, OpenRouterLLM  # noqa: E402
from mcp_servers.rag_pill.schemas import QAPill  # noqa: E402

ENGINES = [
    ("chroma_baseline", ChromaBaselineEngine),
    ("haystack",        HaystackEngine),
    ("txtai",           TxtaiEngine),
]

UPLOADED = (
    "ZORBLIX is a fictional protocol for synchronizing penguins across timezones. "
    "ZORBLIX uses a 7-bit checksum and runs over UDP port 4242. "
    "The ZORBLIX handshake is initiated by the colder party."
)


def _qa_pill() -> QAPill:
    return QAPill(
        name="demo",
        task_type="qa",
        top_k=3,
        rerank=False,
        cite_sources=False,
        chunk_size=400,
        chunk_overlap=40,
        temperature=0.0,
    )


async def _run_one(name: str, engine_cls, scenario: str, task: str, goal: str, doc: str):
    cache = IndexCache(max_entries=4)
    engine = engine_cls(cache, llm=OpenRouterLLM(), embedding_config=EmbeddingConfig.from_env())
    answer = await engine.execute(_qa_pill(), task=task, goal=goal, document_content=doc)
    print(f"\n{'═' * 80}")
    print(f"  ENGINE: {name}    SCENARIO: {scenario}")
    print(f"  Q: {task} {goal}")
    print(f"{'─' * 80}")
    print(answer.strip())
    print(f"{'═' * 80}")


async def main():
    for name, cls in ENGINES:
        await _run_one(
            name, cls, "uploaded ZORBLIX",
            task="What", goal="port does ZORBLIX use?", doc=UPLOADED,
        )
    for name, cls in ENGINES:
        await _run_one(
            name, cls, "bundled corpus",
            task="In Python,", goal="what is async/await used for?", doc="",
        )


if __name__ == "__main__":
    asyncio.run(main())
