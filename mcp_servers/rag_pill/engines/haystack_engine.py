"""Haystack engine adapter — InMemoryDocumentStore + dense retrieval.

Indexing/retrieval via Haystack 2.x components; generation via LLMProvider.
Lazy-imports haystack so a missing install yields SUPPORTS = set() instead
of crashing on module load.
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
from mcp_servers.rag_pill.providers.embedding_validator import (
    validate_document_embeddings,
    validate_query_embedding,
)
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

    async def _build_index(self, pill: Pill, corpus: Any):
        loop = asyncio.get_event_loop()

        def _build():
            store = InMemoryDocumentStore()
            raw_docs = [
                Document(
                    content=doc.text,
                    meta={
                        "source": doc.id.removesuffix(".md") or doc.id,
                        "doc_id": doc.id,
                    },
                )
                for doc in corpus.iter_documents()
            ]
            splitter = DocumentSplitter(
                split_by="word",
                split_length=max(1, pill.chunk_size // 5),  # words ≈ chars/5
                split_overlap=max(0, pill.chunk_overlap // 5),
            )
            splitter.warm_up()
            chunks = splitter.run(documents=raw_docs)["documents"]

            embedder = OpenAIDocumentEmbedder(
                api_key=Secret.from_token(self._embed.api_key),
                api_base_url=self._embed.base_url,
                model=pill.embedder,
            )
            embedded = validate_document_embeddings(embedder.run(documents=chunks))["documents"]
            store.write_documents(embedded)
            return store

        return await loop.run_in_executor(None, _build)

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
        emitter.emit("ingest_start")
        store = await self._cache.get_or_build(
            key, lambda: self._build_index(pill, resolved)
        )
        emitter.emit("ingest_done")

        top_k = getattr(pill, "top_k", 3)
        query = f"{task} {goal}"
        emitter.emit("retrieval_start")

        def _retrieve():
            text_embedder = OpenAITextEmbedder(
                api_key=Secret.from_token(self._embed.api_key),
                api_base_url=self._embed.base_url,
                model=pill.embedder,
            )
            q_emb = validate_query_embedding(text_embedder.run(text=query))["embedding"]
            retriever = InMemoryEmbeddingRetriever(document_store=store, top_k=top_k)
            return retriever.run(query_embedding=q_emb)["documents"]

        t0 = time.perf_counter()
        docs = await asyncio.get_event_loop().run_in_executor(None, _retrieve)
        retrieval_latency_ms = int((time.perf_counter() - t0) * 1000)
        emitter.emit("retrieval_done", took_ms=retrieval_latency_ms)

        spans: list = []
        unlocated = 0
        for rank, d in enumerate(docs):
            doc_id = (d.meta or {}).get("doc_id", "")
            score = getattr(d, "score", None)
            span = locate_span(resolved, doc_id, d.content, score=score, rank=rank)
            if span is None:
                unlocated += 1
            else:
                spans.append(span)

        context = "\n\n---\n\n".join(d.content for d in docs)
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
