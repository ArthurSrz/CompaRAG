"""Chroma + naive retriever — interpretable baseline for the arena.

Deliberately minimal: char-window chunking, OpenAI embeddings via Chroma's
embedding function, top-k cosine retrieval. No reranker, no query rewrite,
no hybrid search. The point is to give the arena a *floor* — quality deltas
between sophisticated engines and this one are then interpretable as
attributable to retrieval sophistication, not just framework choice.
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

try:
    import chromadb
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

# chromadb 1.x routes EphemeralClient through a process-global SharedSystemClient
# cache keyed by 'ephemeral'. Two parallel arena sides each calling
# `chromadb.EphemeralClient()` from different threadpool workers race that cache
# and surface as either `'RustBindingsAPI' object has no attribute 'bindings'`
# (system handed out before bindings finished initializing) or `KeyError:
# 'ephemeral'` (cache evicted between lookup and use). One shared client +
# serialized first-touch eliminates the race; collection names are already
# namespaced by pill + corpus hash, so isolation is preserved.
_CLIENT: Any = None
_CLIENT_LOCK = asyncio.Lock()


async def _get_shared_client() -> Any:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    async with _CLIENT_LOCK:
        if _CLIENT is None:
            loop = asyncio.get_event_loop()
            _CLIENT = await loop.run_in_executor(None, chromadb.EphemeralClient)
    return _CLIENT


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if chunk_size <= 0:
        return [text]
    step = max(1, chunk_size - chunk_overlap)
    return [text[i : i + chunk_size] for i in range(0, len(text), step)] or [""]


def _resolve_corpus(document_content: str, corpus: Any) -> Any | None:
    """Bridge legacy document_content (str) -> HaystackCorpus.

    Precedence:
      1. Explicit `corpus` argument (slice 2.10+ callers).
      2. Non-empty document_content -> EphemeralCorpus (legacy sandbox path).
      3. CORPUS_DIR if it exists -> FixedCorpus (legacy benchmark fallback).
      4. None -> caller returns "no documents available".
    """
    if corpus is not None:
        return corpus
    if document_content.strip():
        return EphemeralCorpus(document_content)
    if CORPUS_DIR.exists():
        return FixedCorpus(CORPUS_DIR)
    return None


class ChromaBaselineEngine:
    id = "chroma_baseline"
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
        client = await _get_shared_client()

        def _build():
            embed_fn = OpenAIEmbeddingFunction(
                api_key=self._embed.api_key,
                api_base=self._embed.base_url,
                model_name=pill.embedder,
            )
            # Idempotent build (see prior comment block): get_or_create +
            # upsert keep the build safe to repeat across retry attempts.
            collection = client.get_or_create_collection(
                name=f"baseline_{pill.name}_{corpus.version_hash[:16]}",
                embedding_function=embed_fn,
            )

            ids: list[str] = []
            docs: list[str] = []
            metas: list[dict] = []
            for doc in corpus.iter_documents():
                src = doc.id.removesuffix(".md") or doc.id
                for i, chunk in enumerate(
                    _chunk_text(doc.text, pill.chunk_size, pill.chunk_overlap)
                ):
                    if not chunk.strip():
                        continue
                    ids.append(f"{src}-{i}")
                    docs.append(chunk)
                    metas.append({"source": src, "doc_id": doc.id})

            if not ids:
                return collection
            # chromadb's OpenAIEmbeddingFunction has no batch_size knob; it
            # sends each upsert call's full input list in one embedding
            # request. Split the upsert into batches manually so we don't
            # hand OpenRouter a 70-input call (empty-data flake territory).
            batch = self._embed.batch_size
            for i in range(0, len(ids), batch):
                collection.upsert(
                    ids=ids[i : i + batch],
                    documents=docs[i : i + batch],
                    metadatas=metas[i : i + batch],
                )
            return collection

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
        """Back-compat string-only return — calls execute_with_spans and
        returns just the answer. Existing retry.py + server.py callers stay
        green; arena callers use execute_with_spans for retrieval metrics."""
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
        collection = await self._cache.get_or_build(
            key, lambda: self._build_index(pill, resolved)
        )
        emitter.emit("ingest_done", cache_hit=cache_hit)

        top_k = getattr(pill, "top_k", 3)
        query = f"{task} {goal}"
        emitter.emit("retrieval_start")
        n_items = collection.count()
        if n_items == 0:
            return EngineResult(
                answer="No documents available to search.",
                retrieved_spans=(),
                retrieval_latency_ms=0,
                generation_latency_ms=0,
            )

        t0 = time.perf_counter()
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: collection.query(
                query_texts=[query], n_results=min(top_k, n_items)
            ),
        )
        retrieval_latency_ms = int((time.perf_counter() - t0) * 1000)
        emitter.emit("retrieval_done", took_ms=retrieval_latency_ms)

        chunks = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        spans: list = []
        unlocated = 0
        for rank, chunk_text in enumerate(chunks):
            meta = metas[rank] if rank < len(metas) else {}
            dist = distances[rank] if rank < len(distances) else None
            score = (1.0 - dist) if isinstance(dist, (int, float)) else None
            doc_id = meta.get("doc_id", "")
            span = locate_span(
                resolved, doc_id, chunk_text, score=score, rank=rank
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
