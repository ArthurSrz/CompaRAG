"""txtai engine adapter — txtai Embeddings DB for indexing + retrieval.

txtai bundles an embeddings store and retriever in one tight library.
Generation routes through LLMProvider so the LLM stays invariant across
the arena.
"""

import asyncio
import time
from pathlib import Path
from typing import Any

import numpy as np

from mcp_servers.rag_pill.cache import IndexCache
from mcp_servers.rag_pill.corpus.ephemeral import EphemeralCorpus
from mcp_servers.rag_pill.corpus.fixed import FixedCorpus
from mcp_servers.rag_pill.engines.base import locate_span
from mcp_servers.rag_pill.engines.result import EngineResult
from mcp_servers.rag_pill.progress import NullEmitter, ProgressEmitter
from mcp_servers.rag_pill.providers import EmbeddingConfig, LLMProvider
from mcp_servers.rag_pill.schemas import Pill
from mcp_servers.rag_pill.strategies import render_prompt


_DOC_ID_SEP = "::"  # txtai row id format: f"{doc_id}{SEP}{chunk_idx_in_doc}"

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
    from txtai.embeddings import Embeddings

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Naive char-window chunker — txtai accepts arbitrary strings."""
    if chunk_size <= 0:
        return [text]
    step = max(1, chunk_size - chunk_overlap)
    return [text[i : i + chunk_size] for i in range(0, len(text), step)] or [""]


class TxtaiEngine:
    id = "txtai"
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
            rows: list[tuple[str, str, None]] = []
            for doc in corpus.iter_documents():
                chunk_idx = 0
                for chunk in _chunk_text(doc.text, pill.chunk_size, pill.chunk_overlap):
                    if chunk.strip():
                        # Encode doc_id in the row id so retrieval can recover it
                        # for span projection. Int uids would lose this mapping.
                        rows.append((f"{doc.id}{_DOC_ID_SEP}{chunk_idx}", chunk, None))
                        chunk_idx += 1

            # Use a transform callable so txtai never tries to load the model locally.
            # txtai's provider auto-detection only works for local HuggingFace models;
            # for API-backed embeddings the safest path is an explicit transform.
            import openai as _openai

            _client = _openai.OpenAI(
                api_key=self._embed.api_key,
                base_url=self._embed.base_url or None,
            )

            def _embed_fn(inputs: list[str]) -> np.ndarray:
                resp = _client.embeddings.create(model=pill.embedder, input=inputs)
                return np.array([e.embedding for e in resp.data], dtype=np.float32)

            # method=external is required: without it txtai ignores `transform`
            # and falls back to the default transformers backend, which tries
            # to load `pill.embedder` from HuggingFace and errors with
            # "openai/text-embedding-3-small is not a valid model identifier".
            embeddings = Embeddings(
                {"method": "external", "transform": _embed_fn, "content": True}
            )
            embeddings.index(rows)
            return embeddings

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
        embeddings = await self._cache.get_or_build(
            key, lambda: self._build_index(pill, resolved)
        )
        emitter.emit("ingest_done")

        top_k = getattr(pill, "top_k", 3)
        query = f"{task} {goal}"

        emitter.emit("retrieval_start")
        t0 = time.perf_counter()
        results = await asyncio.get_event_loop().run_in_executor(
            None, lambda: embeddings.search(query, top_k)
        )
        retrieval_latency_ms = int((time.perf_counter() - t0) * 1000)
        emitter.emit("retrieval_done", took_ms=retrieval_latency_ms)

        # txtai returns list[dict] with content=True, else list[(id, score)].
        chunks: list[str] = []
        spans: list = []
        unlocated = 0
        for rank, r in enumerate(results):
            if isinstance(r, dict):
                chunk_text = r.get("text", "")
                row_id = str(r.get("id", ""))
                score = r.get("score")
            else:
                row_id, chunk_text = str(r[0]), str(r[1])
                score = None
            chunks.append(chunk_text)
            doc_id = row_id.split(_DOC_ID_SEP, 1)[0] if _DOC_ID_SEP in row_id else ""
            span = locate_span(
                resolved, doc_id, chunk_text,
                score=score if isinstance(score, (int, float)) else None,
                rank=rank,
            )
            if span is None:
                unlocated += 1
            else:
                spans.append(span)

        context = "\n\n---\n\n".join(chunks)
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
