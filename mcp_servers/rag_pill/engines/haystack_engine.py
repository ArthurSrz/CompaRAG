"""Haystack engine adapter — InMemoryDocumentStore + dense retrieval.

Indexing/retrieval via Haystack 2.x components; generation via LLMProvider.
Lazy-imports haystack so a missing install yields SUPPORTS = set() instead
of crashing on module load.
"""

import asyncio
from pathlib import Path

from mcp_servers.rag_pill.cache import IndexCache, doc_hash
from mcp_servers.rag_pill.providers import EmbeddingConfig, LLMProvider
from mcp_servers.rag_pill.schemas import Pill
from mcp_servers.rag_pill.strategies import render_prompt

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"

try:
    from haystack import Document
    from haystack.components.embedders import (
        OpenAIDocumentEmbedder,
        OpenAITextEmbedder,
    )
    from haystack.components.preprocessors import DocumentSplitter
    from haystack.components.retrievers.in_memory import InMemoryEmbeddingRetriever
    from haystack.document_stores.in_memory import InMemoryDocumentStore
    from haystack.utils import Secret

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class HaystackEngine:
    id = "haystack"
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
            store = InMemoryDocumentStore()
            if document_content.strip():
                raw_docs = [Document(content=document_content, meta={"source": "uploaded"})]
            else:
                raw_docs = [
                    Document(content=p.read_text(), meta={"source": p.stem})
                    for p in CORPUS_DIR.glob("*.md")
                ]
            splitter = DocumentSplitter(
                split_by="word",
                split_length=max(1, pill.chunk_size // 5),  # words ≈ chars/5
                split_overlap=max(0, pill.chunk_overlap // 5),
            )
            splitter.warm_up()
            chunks = splitter.run(documents=raw_docs)["documents"]

            embed_model_id = pill.embedder.split("/", 1)[-1]  # strip "openai/" prefix
            embedder = OpenAIDocumentEmbedder(
                api_key=Secret.from_token(self._embed.api_key),
                api_base_url=self._embed.base_url,
                model=embed_model_id,
            )
            embedded = embedder.run(documents=chunks)["documents"]
            store.write_documents(embedded)
            return store

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
        store = await self._cache.get_or_build(
            key, lambda: self._build_index(pill, document_content)
        )

        top_k = getattr(pill, "top_k", 3)
        query = f"{task} {goal}"

        def _retrieve():
            text_embedder = OpenAITextEmbedder(
                api_key=Secret.from_token(self._embed.api_key),
                api_base_url=self._embed.base_url,
                model=pill.embedder.split("/", 1)[-1],  # strip "openai/" prefix
            )
            q_emb = text_embedder.run(text=query)["embedding"]
            retriever = InMemoryEmbeddingRetriever(document_store=store, top_k=top_k)
            return retriever.run(query_embedding=q_emb)["documents"]

        docs = await asyncio.get_event_loop().run_in_executor(None, _retrieve)
        context = "\n\n---\n\n".join(d.content for d in docs)

        prompt = render_prompt(pill, context, task, goal)
        return await self._llm.invoke(pill, prompt)
