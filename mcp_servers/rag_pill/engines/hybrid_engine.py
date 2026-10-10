"""
BUT : fusionner la recherche par mots exacts et la recherche par sens —
ce que fait l'industrie, et ce que l'arène ne savait pas mesurer.

Hybrid engine adapter — BM25 and dense retrieval fused by reciprocal rank.

The two signals fail on opposite inputs. A dense retriever finds the chunk
that *means* the right thing and misses the one that merely says it;
BM25 finds the exact term and misses its synonym. Fusing them is the
default of most production RAG stacks, and the arena had no way to show
whether that default earns its complexity.

Fusion is by rank, never by score. A BM25 score and a cosine similarity
live on incomparable scales, and the usual way hybrid retrieval goes
quietly wrong is a normalization that makes one of them dominate. RRF only
ever reads positions — see `engines/lexical.reciprocal_rank_fusion`.

Both halves retrieve over the SAME chunks, produced by the same chunker, so
the comparison isolates the retrieval signal rather than smuggling in a
second variable. It also means spans are exact and
`unlocated_span_count` is structurally zero.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import numpy as np

from mcp_servers.rag_pill.cache import IndexCache
from mcp_servers.rag_pill.corpus.ephemeral import EphemeralCorpus
from mcp_servers.rag_pill.corpus.fixed import FixedCorpus
from mcp_servers.rag_pill.engines.bm25_engine import build_spans
from mcp_servers.rag_pill.engines.chunking import chunk_corpus
from mcp_servers.rag_pill.engines.lexical import BM25Index, reciprocal_rank_fusion
from mcp_servers.rag_pill.engines.result import EngineResult
from mcp_servers.rag_pill.progress import NullEmitter, ProgressEmitter
from mcp_servers.rag_pill.providers import EmbeddingConfig, LLMProvider
from mcp_servers.rag_pill.providers.embedding_validator import validate_vector_list
from mcp_servers.rag_pill.schemas import Pill
from mcp_servers.rag_pill.strategies import render_prompt

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"

# Each ranker contributes this many candidates to the fusion. Wider than
# top_k on purpose: fusion can only promote what at least one ranker
# surfaced, so a pool equal to top_k would make RRF a no-op whenever the two
# rankers already agree.
CANDIDATE_POOL_MULTIPLIER = 4
MIN_CANDIDATE_POOL = 20


def _resolve_corpus(document_content: str, corpus: Any) -> Any | None:
    """See chroma_baseline_engine._resolve_corpus — same precedence rules."""
    if corpus is not None:
        return corpus
    if document_content.strip():
        return EphemeralCorpus(document_content)
    if CORPUS_DIR.exists():
        return FixedCorpus(CORPUS_DIR)
    return None


def cosine_ranking(query_vector: np.ndarray, matrix: np.ndarray, pool: int) -> list[int]:
    """Indices of the `pool` nearest rows, best first."""
    if matrix.size == 0:
        return []
    normalized = matrix / np.clip(
        np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12, None
    )
    query = query_vector / max(float(np.linalg.norm(query_vector)), 1e-12)
    similarities = normalized @ query
    return list(np.argsort(-similarities)[:pool])


class HybridEngine:
    id = "hybrid"
    SUPPORTS: set[str] = {"summary", "qa"}

    def __init__(
        self,
        cache: IndexCache,
        llm: LLMProvider,
        embedding_config: EmbeddingConfig,
        embed_fn=None,
    ) -> None:
        self._cache = cache
        self._llm = llm
        self._embed = embedding_config
        # Injectable for tests; production builds an OpenAI-compatible client
        # and fans the inputs through the shared batched_embed retry path.
        self._embed_fn = embed_fn

    def _embed_texts(self, model: str, inputs: list[str]) -> np.ndarray:
        if self._embed_fn is not None:
            return np.asarray(self._embed_fn(inputs), dtype=np.float32)

        import openai  # noqa: PLC0415

        from mcp_servers.rag_pill.providers.batched_embed import (  # noqa: PLC0415
            batched_embed,
        )

        client = openai.OpenAI(
            api_key=self._embed.api_key, base_url=self._embed.base_url or None
        )
        vectors = batched_embed(
            client,
            model=model,
            inputs=inputs,
            batch_size=self._embed.batch_size,
        )
        # Same boundary check the other engines apply: a degraded OpenRouter
        # response raises the retry marker here rather than producing a
        # silently wrong ranking downstream.
        validate_vector_list(vectors.tolist())
        return vectors

    async def _build_index(self, pill: Pill, corpus: Any):
        loop = asyncio.get_running_loop()

        def _build():
            chunks = chunk_corpus(corpus, pill.chunk_size, pill.chunk_overlap)
            if not chunks:
                return chunks, BM25Index([]), np.zeros((0, 0), dtype=np.float32)
            texts = [c.text for c in chunks]
            return chunks, BM25Index(texts), self._embed_texts(pill.embedder, texts)

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
        cache_hit = self._cache.has(key)
        emitter.emit("ingest_start")
        chunks, bm25, matrix = await self._cache.get_or_build(
            key, lambda: self._build_index(pill, resolved)
        )
        emitter.emit("ingest_done", cache_hit=cache_hit)

        top_k = getattr(pill, "top_k", 3)
        query = f"{task} {goal}"
        pool = max(MIN_CANDIDATE_POOL, top_k * CANDIDATE_POOL_MULTIPLIER)

        emitter.emit("retrieval_start")
        t0 = time.perf_counter()
        lexical_ranking = [index for index, _ in bm25.rank(query, pool)]
        loop = asyncio.get_running_loop()
        query_vector = await loop.run_in_executor(
            None, lambda: self._embed_texts(pill.embedder, [query])
        )
        dense_ranking = (
            cosine_ranking(np.asarray(query_vector)[0], matrix, pool)
            if len(chunks)
            else []
        )
        fused = reciprocal_rank_fusion([lexical_ranking, dense_ranking])[:top_k]
        retrieval_latency_ms = int((time.perf_counter() - t0) * 1000)
        emitter.emit("retrieval_done", took_ms=retrieval_latency_ms)

        spans = build_spans(chunks, fused)
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
