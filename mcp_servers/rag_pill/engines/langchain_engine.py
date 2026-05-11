"""LangChain engine adapter — index + retrieve via LangChain/FAISS, generate via LLMProvider.

Prompt construction lives in mcp_servers/rag_pill/strategies/; OpenRouter
wiring lives in mcp_servers/rag_pill/providers/. This module is responsible
only for framework-specific indexing and retrieval — the bits that actually
differ between LangChain, LlamaIndex, Haystack, etc.
"""

import asyncio
import time
from pathlib import Path
from typing import Any

from mcp_servers.rag_pill.cache import IndexCache
from mcp_servers.rag_pill.corpus.ephemeral import EphemeralCorpus
from mcp_servers.rag_pill.corpus.fixed import FixedCorpus
from mcp_servers.rag_pill.engines.base import locate_span
from mcp_servers.rag_pill.engines.result import EngineResult
from mcp_servers.rag_pill.progress import NullEmitter, ProgressEmitter
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
        return OpenAIEmbeddings(
            model=pill.embedder,
            base_url=self._embed.base_url,
            openai_api_key=self._embed.api_key,
        )

    async def _build_index(self, pill: Pill, corpus: Any):
        loop = asyncio.get_event_loop()
        splitter = self._splitter(pill)
        embeddings = self._embeddings(pill)

        docs = [
            LCDocument(
                page_content=doc.text,
                metadata={
                    "source": doc.id.removesuffix(".md") or doc.id,
                    "doc_id": doc.id,
                },
            )
            for doc in corpus.iter_documents()
        ]
        chunks = splitter.split_documents(docs)

        return await loop.run_in_executor(
            None, lambda: FAISS.from_documents(chunks, embeddings)
        )

    async def execute(
        self,
        pill: Pill,
        task: str,
        goal: str,
        document_content: str = "",
        corpus: Any = None,
        progress: ProgressEmitter | None = None,
    ) -> str:
        """Back-compat thin wrapper — see chroma_baseline_engine.execute."""
        result = await self.execute_with_spans(
            pill, task, goal, document_content=document_content, corpus=corpus,
            progress=progress,
        )
        return result.answer

    async def execute_with_spans(
        self,
        pill: Pill,
        task: str,
        goal: str,
        document_content: str = "",
        corpus: Any = None,
        progress: ProgressEmitter | None = None,
    ) -> EngineResult:
        emitter: ProgressEmitter = progress or NullEmitter()
        resolved = _resolve_corpus(document_content, corpus)
        if resolved is None:
            return EngineResult(
                answer="No documents available to search.",
                retrieved_spans=(),
                retrieval_latency_ms=0,
                generation_latency_ms=0,
            )

        key = (
            self.id,
            pill.embedder,
            pill.chunk_size,
            pill.chunk_overlap,
            resolved.version_hash,
        )
        cache_hit = self._cache.has(key)
        emitter.emit("ingest_start")
        vectorstore = await self._cache.get_or_build(
            key, lambda: self._build_index(pill, resolved)
        )
        emitter.emit("ingest_done", cache_hit=cache_hit)

        top_k = getattr(pill, "top_k", 3)
        retriever = vectorstore.as_retriever(search_kwargs={"k": top_k})
        query = f"{task} {goal}"

        emitter.emit("retrieval_start")
        t0 = time.perf_counter()
        results = retriever.invoke(query)
        retrieval_latency_ms = int((time.perf_counter() - t0) * 1000)
        emitter.emit("retrieval_done", took_ms=retrieval_latency_ms)

        spans: list = []
        unlocated = 0
        for rank, d in enumerate(results):
            doc_id = (d.metadata or {}).get("doc_id", "")
            score = (d.metadata or {}).get("score")
            if not isinstance(score, (int, float)):
                score = None
            span = locate_span(
                resolved, doc_id, d.page_content, score=score, rank=rank
            )
            if span is None:
                unlocated += 1
            else:
                spans.append(span)

        context = "\n\n---\n\n".join(d.page_content for d in results)
        prompt = render_prompt(pill, context, task, goal)
        emitter.emit("mediation_start")
        t1 = time.perf_counter()
        answer = await self._llm.invoke(pill, prompt)
        generation_latency_ms = int((time.perf_counter() - t1) * 1000)
        emitter.emit("mediation_done", took_ms=generation_latency_ms)

        return EngineResult(
            answer=answer,
            retrieved_spans=tuple(spans),
            retrieval_latency_ms=retrieval_latency_ms,
            generation_latency_ms=generation_latency_ms,
            unlocated_span_count=unlocated,
        )
