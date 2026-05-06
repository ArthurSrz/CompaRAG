"""LangChain engine adapter — index + retrieve via LangChain/FAISS, generate via LLMProvider.

Prompt construction lives in mcp_servers/rag_pill/strategies/; OpenRouter
wiring lives in mcp_servers/rag_pill/providers/. This module is responsible
only for framework-specific indexing and retrieval — the bits that actually
differ between LangChain, LlamaIndex, Haystack, etc.
"""

import asyncio
from pathlib import Path

from mcp_servers.rag_pill.cache import IndexCache, doc_hash
from mcp_servers.rag_pill.providers import EmbeddingConfig, LLMProvider
from mcp_servers.rag_pill.schemas import Pill
from mcp_servers.rag_pill.strategies import render_prompt

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"

try:
    from langchain_community.document_loaders import DirectoryLoader, TextLoader
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document as LCDocument
    from langchain_openai import OpenAIEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class LangChainEngine:
    id = "langchain"
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

    def _splitter(self, pill: Pill):
        return RecursiveCharacterTextSplitter(
            chunk_size=pill.chunk_size, chunk_overlap=pill.chunk_overlap
        )

    def _embeddings(self, pill: Pill):
        # Strip provider prefix ("openai/…" → "…") — OpenRouter's embeddings
        # endpoint rejects prefixed names, same as txtai/chroma engines.
        embed_model_id = pill.embedder.split("/", 1)[-1]
        return OpenAIEmbeddings(
            model=embed_model_id,
            base_url=self._embed.base_url,
            openai_api_key=self._embed.api_key,
        )

    async def _build_index(self, pill: Pill, document_content: str):
        loop = asyncio.get_event_loop()
        splitter = self._splitter(pill)
        embeddings = self._embeddings(pill)

        if document_content.strip():
            doc = LCDocument(page_content=document_content, metadata={"source": "uploaded"})
            chunks = splitter.split_documents([doc])
        else:
            loader = DirectoryLoader(str(CORPUS_DIR), glob="*.md", loader_cls=TextLoader)
            docs = loader.load()
            chunks = splitter.split_documents(docs)

        return await loop.run_in_executor(
            None, lambda: FAISS.from_documents(chunks, embeddings)
        )

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
        vectorstore = await self._cache.get_or_build(
            key, lambda: self._build_index(pill, document_content)
        )

        top_k = getattr(pill, "top_k", 3)
        retriever = vectorstore.as_retriever(search_kwargs={"k": top_k})
        query = f"{task} {goal}"
        results = retriever.invoke(query)
        context = "\n\n---\n\n".join(d.page_content for d in results)

        prompt = render_prompt(pill, context, task, goal)
        return await self._llm.invoke(pill, prompt)
