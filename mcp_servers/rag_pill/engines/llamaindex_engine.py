"""LlamaIndex engine adapter — index + retrieve via LlamaIndex, generate via LLMProvider.

Bypasses LlamaIndex's `as_query_engine().query()` so the LLM seam is the same
LLMProvider every other engine uses. The arena is comparing *retrieval
pipelines* (Tool varies) under a constant LLM (Agent invariant) — wiring the
LlamaIndex query engine to its own LLM would violate that invariant.
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
        # embed_batch_size caps inputs per API call; the default (10) is
        # small but not low enough on degraded OpenRouter. Use the shared
        # EmbeddingConfig.batch_size knob so the operator can dial it.
        Settings.embed_model = OpenAILikeEmbedding(
            model_name=pill.embedder,
            api_base=self._embed.base_url,
            api_key=self._embed.api_key,
            embed_batch_size=self._embed.batch_size,
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
        self._configure(pill)
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
        index = await self._cache.get_or_build(
            key, lambda: self._build_index(pill, resolved)
        )
        emitter.emit("ingest_done", cache_hit=cache_hit)

        top_k = getattr(pill, "top_k", 3)
        query = f"{task} {goal}"
        retriever = index.as_retriever(similarity_top_k=top_k)

        emitter.emit("retrieval_start")
        t0 = time.perf_counter()
        nodes = await asyncio.get_event_loop().run_in_executor(
            None, lambda: retriever.retrieve(query)
        )
        retrieval_latency_ms = int((time.perf_counter() - t0) * 1000)
        emitter.emit("retrieval_done", took_ms=retrieval_latency_ms)

        spans: list = []
        unlocated = 0
        for rank, n in enumerate(nodes):
            meta = getattr(n.node, "metadata", {}) or {}
            doc_id = meta.get("doc_id", "")
            score = getattr(n, "score", None)
            span = locate_span(
                resolved, doc_id, n.get_content(), score=score, rank=rank
            )
            if span is None:
                unlocated += 1
            else:
                spans.append(span)

        context = "\n\n---\n\n".join(n.get_content() for n in nodes)
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
