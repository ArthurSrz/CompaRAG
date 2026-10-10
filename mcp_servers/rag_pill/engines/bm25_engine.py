"""
BUT : faire concourir la recherche lexicale pure — aucun embedding, aucun
appel d'API à l'indexation, le classement par mots exacts.

BM25 engine adapter — the arena's lexical floor.

Every other engine but ColPali retrieves by embedding similarity. Without a
lexical contestant the arena cannot answer the question underneath all the
others: *do the embeddings earn their cost?* BM25 is the control. It indexes
in milliseconds, costs nothing, calls no API, and on the queries it suits —
jargon, proper nouns, part numbers, error codes, anything a dense model
smooths into its neighbours — it is very hard to beat.

It also makes a second measurement possible. BM25 and a dense retriever fail
on opposite inputs, so the gap between this engine and the dense ones *per
query* says more about a corpus than either score alone.

Chunking happens in `engines/chunking.py`, so every span is exact and
`unlocated_span_count` is structurally zero.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from mcp_servers.rag_pill.cache import IndexCache
from mcp_servers.rag_pill.corpus.ephemeral import EphemeralCorpus
from mcp_servers.rag_pill.corpus.fixed import FixedCorpus
from mcp_servers.rag_pill.engines.chunking import Chunk, chunk_corpus
from mcp_servers.rag_pill.engines.lexical import BM25Index
from mcp_servers.rag_pill.engines.result import EngineResult, RetrievedSpan
from mcp_servers.rag_pill.progress import NullEmitter, ProgressEmitter
from mcp_servers.rag_pill.providers import EmbeddingConfig, LLMProvider
from mcp_servers.rag_pill.schemas import Pill
from mcp_servers.rag_pill.strategies import render_prompt

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"

# BM25 has no embedder. The cache key's embedder slot still has to be filled,
# and a literal is more honest than threading pill.embedder through a code
# path that never reads it.
_NO_EMBEDDER = "none"


def _resolve_corpus(document_content: str, corpus: Any) -> Any | None:
    """See chroma_baseline_engine._resolve_corpus — same precedence rules."""
    if corpus is not None:
        return corpus
    if document_content.strip():
        return EphemeralCorpus(document_content)
    if CORPUS_DIR.exists():
        return FixedCorpus(CORPUS_DIR)
    return None


def build_spans(chunks: list[Chunk], ranked: list[tuple[int, float]]) -> tuple:
    """Project ranked chunk indices onto RetrievedSpans.

    Shared with the hybrid engine. No `locate_span()` call: the chunker
    already knows where it cut, so the offsets are exact rather than
    recovered by string search.
    """
    return tuple(
        RetrievedSpan(
            source_doc_id=chunks[index].doc_id,
            char_start=chunks[index].char_start,
            char_end=chunks[index].char_end,
            text=chunks[index].text,
            score=score,
            rank=rank,
        )
        for rank, (index, score) in enumerate(ranked)
    )


class BM25Engine:
    id = "bm25"
    SUPPORTS: set[str] = {"summary", "qa"}

    def __init__(
        self,
        cache: IndexCache,
        llm: LLMProvider,
        embedding_config: EmbeddingConfig | None = None,
    ) -> None:
        self._cache = cache
        self._llm = llm
        # Accepted for construction symmetry with the other engines and
        # never used — that absence is the paradigm.
        self._embed = embedding_config

    async def _build_index(self, pill: Pill, corpus: Any):
        loop = asyncio.get_running_loop()

        def _build():
            chunks = chunk_corpus(corpus, pill.chunk_size, pill.chunk_overlap)
            return chunks, BM25Index([c.text for c in chunks])

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
            _NO_EMBEDDER,
            pill.chunk_size,
            pill.chunk_overlap,
            resolved.version_hash,
        )
        cache_hit = self._cache.has(key)
        emitter.emit("ingest_start")
        chunks, index = await self._cache.get_or_build(
            key, lambda: self._build_index(pill, resolved)
        )
        emitter.emit("ingest_done", cache_hit=cache_hit)

        top_k = getattr(pill, "top_k", 3)
        query = f"{task} {goal}"

        emitter.emit("retrieval_start")
        t0 = time.perf_counter()
        ranked = index.rank(query, top_k)
        retrieval_latency_ms = int((time.perf_counter() - t0) * 1000)
        emitter.emit("retrieval_done", took_ms=retrieval_latency_ms)

        spans = build_spans(chunks, ranked)
        context = "\n\n---\n\n".join(span.text for span in spans)
        prompt = render_prompt(pill, context, task, goal)
        emitter.emit("mediation_start")
        t1 = time.perf_counter()
        answer = await self._llm.invoke(pill, prompt)
        generation_latency_ms = int((time.perf_counter() - t1) * 1000)
        emitter.emit("mediation_done", took_ms=generation_latency_ms)

        return EngineResult(
            answer=answer,
            retrieved_spans=spans,
            retrieval_latency_ms=retrieval_latency_ms,
            generation_latency_ms=generation_latency_ms,
            unlocated_span_count=0,
        )
