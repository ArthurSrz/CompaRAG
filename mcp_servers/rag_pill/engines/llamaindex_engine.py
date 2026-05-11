"""LlamaIndex engine adapter — index + retrieve via LlamaIndex, generate via LLMProvider.

Bypasses LlamaIndex's `as_query_engine().query()` so the LLM seam is the same
LLMProvider every other engine uses. The arena is comparing *retrieval
pipelines* (Tool varies) under a constant LLM (Agent invariant) — wiring the
LlamaIndex query engine to its own LLM would violate that invariant.
"""

import asyncio
from pathlib import Path
from typing import Any

from mcp_servers.rag_pill.cache import IndexCache
from mcp_servers.rag_pill.corpus.ephemeral import EphemeralCorpus
from mcp_servers.rag_pill.corpus.fixed import FixedCorpus
from mcp_servers.rag_pill.providers import EmbeddingConfig, LLMProvider
from mcp_servers.rag_pill.schemas import Pill
from mcp_servers.rag_pill.strategies import render_prompt

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"


def _resolve_corpus(document_content: str, corpus: Any) -> Any | None:
    """See chroma_baseline_engine._resolve_corpus — same precedence rules."""
    if corpus is not None:
        return corpus
    if document_content.strip():
        return EphemeralCorpus(document_content)
    if CORPUS_DIR.exists():
        return FixedCorpus(CORPUS_DIR)
    return None

try:
    from llama_index.core import Document, Settings, VectorStoreIndex
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.embeddings.openai_like import OpenAILikeEmbedding

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class LlamaIndexEngine:
    id = "llamaindex"
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

    def _configure(self, pill: Pill) -> None:
        Settings.embed_model = OpenAILikeEmbedding(
            model_name=pill.embedder,
            api_base=self._embed.base_url,
            api_key=self._embed.api_key,
        )
        Settings.node_parser = SentenceSplitter(
            chunk_size=pill.chunk_size, chunk_overlap=pill.chunk_overlap
        )

    async def _build_index(self, pill: Pill, corpus: Any):
        loop = asyncio.get_event_loop()
        self._configure(pill)
        docs = [
            Document(
                text=doc.text,
                metadata={
                    "source": doc.id.removesuffix(".md") or doc.id,
                    "doc_id": doc.id,
                },
            )
            for doc in corpus.iter_documents()
        ]
        return await loop.run_in_executor(
            None, lambda: VectorStoreIndex.from_documents(docs)
        )

    async def execute(
        self,
        pill: Pill,
        task: str,
        goal: str,
        document_content: str = "",
        corpus: Any = None,
    ) -> str:
        self._configure(pill)
        resolved = _resolve_corpus(document_content, corpus)
        if resolved is None:
            return "No documents available to search."

        key = (
            self.id,
            pill.embedder,
            pill.chunk_size,
            pill.chunk_overlap,
            resolved.version_hash,
        )
        index = await self._cache.get_or_build(
            key, lambda: self._build_index(pill, resolved)
        )

        top_k = getattr(pill, "top_k", 3)
        query = f"{task} {goal}"
        retriever = index.as_retriever(similarity_top_k=top_k)
        nodes = await asyncio.get_event_loop().run_in_executor(
            None, lambda: retriever.retrieve(query)
        )
        context = "\n\n---\n\n".join(n.get_content() for n in nodes)

        prompt = render_prompt(pill, context, task, goal)
        return await self._llm.invoke(pill, prompt)
