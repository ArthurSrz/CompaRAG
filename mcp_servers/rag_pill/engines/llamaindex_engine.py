"""LlamaIndex engine adapter — lazy-imports llama_index."""

import asyncio
import os
from pathlib import Path

from mcp_servers.rag_pill.cache import IndexCache, doc_hash
from mcp_servers.rag_pill.schemas import Pill, QAPill, SummaryPill

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"

try:
    from llama_index.core import Document, Settings, VectorStoreIndex
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.embeddings.openai import OpenAIEmbedding
    from llama_index.llms.openai_like import OpenAILike

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class LlamaIndexEngine:
    id = "llamaindex"
    SUPPORTS: set[str] = {"summary", "qa"} if _AVAILABLE else set()

    def __init__(self, cache: IndexCache) -> None:
        self._cache = cache
        self._api_key = os.environ["OPENROUTER_API_KEY"]

    def _configure(self, pill: Pill) -> None:
        # LlamaIndex's OpenAIEmbedding validates the model name against a
        # closed enum (OpenAIEmbeddingModelType), so OpenRouter-prefixed names
        # like "openai/text-embedding-3-small" are rejected. Strip the provider
        # prefix; OpenRouter routes by the bare suffix.
        embed_model = pill.embedder.split("/", 1)[1] if "/" in pill.embedder else pill.embedder
        Settings.embed_model = OpenAIEmbedding(
            model=embed_model,
            api_base="https://openrouter.ai/api/v1",
            api_key=self._api_key,
        )
        Settings.llm = OpenAILike(
            model=pill.llm,
            api_base="https://openrouter.ai/api/v1",
            api_key=self._api_key,
            temperature=pill.temperature,
            max_tokens=getattr(pill, "max_output_tokens", 4096),
            is_chat_model=True,
            # LlamaIndex's response synthesizer computes available context as
            # context_window - prompt_tokens - max_tokens. For unknown models
            # it defaults to ~512, which goes negative on real prompts.
            # 32k is conservative for Mistral Medium / GPT-class models.
            context_window=32000,
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

        if isinstance(pill, SummaryPill):
            preamble = (
                f"Provide a {pill.style} summary at ~{int(pill.compression_ratio * 100)}% length. "
            )
        elif isinstance(pill, QAPill):
            preamble = "Answer using only the retrieved context. "
        else:
            preamble = ""

        engine = index.as_query_engine(similarity_top_k=top_k)
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: engine.query(preamble + query)
        )
        return str(response)
