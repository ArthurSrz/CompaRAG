"""LlamaIndex engine adapter — index + retrieve via LlamaIndex, generate via LLMProvider.

Bypasses LlamaIndex's `as_query_engine().query()` so the LLM seam is the same
LLMProvider every other engine uses. The arena is comparing *retrieval
pipelines* (Tool varies) under a constant LLM (Agent invariant) — wiring the
LlamaIndex query engine to its own LLM would violate that invariant.
"""

import asyncio
from pathlib import Path

from mcp_servers.rag_pill.cache import IndexCache, doc_hash
from mcp_servers.rag_pill.providers import EmbeddingConfig, LLMProvider
from mcp_servers.rag_pill.schemas import Pill
from mcp_servers.rag_pill.strategies import render_prompt

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"

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

    async def _build_index(self, pill: Pill, document_content: str):
        loop = asyncio.get_event_loop()
        self._configure(pill)
        if document_content.strip():
            docs = [Document(text=document_content, metadata={"source": "uploaded"})]
        else:
            docs = [
                Document(text=p.read_text(), metadata={"source": p.stem})
                for p in CORPUS_DIR.glob("*.md")
            ]
        return await loop.run_in_executor(
            None, lambda: VectorStoreIndex.from_documents(docs)
        )

    async def execute(
        self, pill: Pill, task: str, goal: str, document_content: str
    ) -> str:
        self._configure(pill)
        key = (
            self.id,
            pill.embedder,
            pill.chunk_size,
            pill.chunk_overlap,
            doc_hash(document_content),
        )
        index = await self._cache.get_or_build(
            key, lambda: self._build_index(pill, document_content)
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
