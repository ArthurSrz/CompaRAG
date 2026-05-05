"""txtai engine adapter — txtai Embeddings DB for indexing + retrieval.

txtai bundles an embeddings store and retriever in one tight library.
Generation routes through LLMProvider so the LLM stays invariant across
the arena.
"""

import asyncio
from pathlib import Path

from mcp_servers.rag_pill.cache import IndexCache, doc_hash
from mcp_servers.rag_pill.providers import EmbeddingConfig, LLMProvider
from mcp_servers.rag_pill.schemas import Pill
from mcp_servers.rag_pill.strategies import render_prompt

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"

try:
    from txtai.embeddings import Embeddings

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Naive char-window chunker — txtai accepts arbitrary strings."""
    if chunk_size <= 0:
        return [text]
    step = max(1, chunk_size - chunk_overlap)
    return [text[i : i + chunk_size] for i in range(0, len(text), step)] or [""]


class TxtaiEngine:
    id = "txtai"
    SUPPORTS: set[str] = {"summary", "qa"} if _AVAILABLE else set()

    def __init__(
        self,
        cache: IndexCache,
        llm: LLMProvider,
        embedding_config: EmbeddingConfig,
    ) -> None:
        self._cache = cache
        self._llm = llm
        self._embed = embedding_config

    async def _build_index(self, pill: Pill, document_content: str):
        loop = asyncio.get_event_loop()

        def _build():
            sources: list[tuple[str, str]] = []  # (source_id, text)
            if document_content.strip():
                sources.append(("uploaded", document_content))
            else:
                for p in CORPUS_DIR.glob("*.md"):
                    sources.append((p.stem, p.read_text()))

            rows: list[tuple[int, str, None]] = []
            uid = 0
            for src, text in sources:
                for chunk in _chunk_text(text, pill.chunk_size, pill.chunk_overlap):
                    if chunk.strip():
                        rows.append((uid, chunk, None))
                        uid += 1

            # Strip provider prefix (e.g. "openai/text-embedding-3-small" → "text-embedding-3-small")
            model_id = pill.embedder.split("/", 1)[-1]
            embeddings = Embeddings(
                {
                    "path": model_id,
                    "provider": "openai",
                    "api": self._embed.base_url,
                    "apikey": self._embed.api_key,
                    "content": True,
                }
            )
            embeddings.index(rows)
            return embeddings

        return await loop.run_in_executor(None, _build)

    async def execute(
        self, pill: Pill, task: str, goal: str, document_content: str
    ) -> str:
        key = (
            self.id,
            pill.embedder,
            pill.chunk_size,
            pill.chunk_overlap,
            doc_hash(document_content),
        )
        embeddings = await self._cache.get_or_build(
            key, lambda: self._build_index(pill, document_content)
        )

        top_k = getattr(pill, "top_k", 3)
        query = f"{task} {goal}"

        results = await asyncio.get_event_loop().run_in_executor(
            None, lambda: embeddings.search(query, top_k)
        )
        # txtai returns list[dict] with content=True, else list[(id, score)].
        chunks = [r["text"] if isinstance(r, dict) else r[1] for r in results]
        context = "\n\n---\n\n".join(chunks)

        prompt = render_prompt(pill, context, task, goal)
        return await self._llm.invoke(pill, prompt)
