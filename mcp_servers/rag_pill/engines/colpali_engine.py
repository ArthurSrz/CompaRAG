"""
BUT : faire concourir ColPali comme RAGEngine — récupération par similarité
visuelle sur les pages rendues, génération par le LLM partagé de l'arène.

ColPali engine adapter — visual late-interaction retrieval over PDF pages.

This is the first engine in the arena whose retrieval signal is not text.
Three consequences, all deliberate:

1. **It is a retriever, not a generator.** ColPali ranks pages by how well
   their *pixels* answer the query, then hands the retrieved pages' *text*
   to the same `LLMProvider` every other engine uses. The arena's core
   invariant — one LLM for all contestants, so a vote measures retrieval —
   survives intact. A vote against ColPali is a vote about visual
   retrieval, not about a different model's prose.

2. **It ignores `pill.embedder`.** Every other engine honours the pill's
   `text-embedding-3-small`; ColPali's encoder *is* the paradigm and cannot
   be swapped for a text embedder without ceasing to be ColPali. This is
   the one parity deviation, and it is the point of the comparison rather
   than a flaw in it. It is surfaced in the engine's display label so the
   BlindReveal does not mislead.

3. **It needs a VisualCorpus.** Pages cannot be recovered from a string:
   the arena's upload path flattens PDFs to text at the border
   (`backend/tool_arena/document/read_uploaded_file_as_text.py`), so a
   `document_content` upload has no pixels left to embed. Corpus mode only,
   until the binary path exists.

`pill.chunk_size` / `chunk_overlap` are likewise unused: the page is the
chunk. That is not an oversight — it is the whole claim ColPali makes,
that a document's native unit beats an arbitrary character window.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from mcp_servers.rag_pill.cache import IndexCache
from mcp_servers.rag_pill.engines.colpali_backend import (
    ColPaliBackend,
    TransformersColPaliBackend,
    maxsim,
)
from mcp_servers.rag_pill.engines.result import EngineResult, RetrievedSpan
from mcp_servers.rag_pill.progress import NullEmitter, ProgressEmitter
from mcp_servers.rag_pill.providers import EmbeddingConfig, LLMProvider
from mcp_servers.rag_pill.schemas import Pill
from mcp_servers.rag_pill.strategies import render_prompt

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"

_NO_PAGES = (
    "No page images available to search. ColPali retrieves over rendered PDF "
    "pages; this run supplied none."
)
_TEXT_ONLY = (
    "This run supplied a text-only document. ColPali retrieves over rendered "
    "PDF pages and cannot search text that has already been flattened."
)

def _probe_dependencies() -> str | None:
    """Return an import-error string, or None when the engine can run.

    Probes only what the *engine* needs: numpy for MaxSim, PyMuPDF to turn
    pages into pixels. The model stack (torch, colpali-engine) is probed
    lazily by TransformersColPaliBackend, because an injected backend — a
    hosted endpoint, or a test fake — may legitimately need neither.
    """
    try:
        import numpy  # noqa: F401, PLC0415
    except ImportError as exc:
        return f"numpy: {exc}"
    try:
        from mcp_servers.rag_pill.corpus.visual import _import_pymupdf  # noqa: PLC0415

        _import_pymupdf()
    except ImportError as exc:
        return f"pymupdf: {exc}"
    return None


_IMPORT_ERROR: str | None = _probe_dependencies()
_AVAILABLE = _IMPORT_ERROR is None

if _AVAILABLE:
    import numpy as np  # noqa: F401


def _resolve_corpus(corpus: Any) -> Any | None:
    """ColPali's narrower version of the shared `_resolve_corpus`.

    Only a corpus exposing `render_pages()` qualifies. The fallback to a
    bare `CORPUS_DIR` that the text engines perform is reproduced here with
    VisualCorpus so that corpus-mode traffic works identically, but there is
    deliberately no EphemeralCorpus branch — see this module's docstring.
    """
    if corpus is not None:
        return corpus if hasattr(corpus, "render_pages") else None
    if CORPUS_DIR.exists():
        from mcp_servers.rag_pill.corpus.visual import VisualCorpus  # noqa: PLC0415

        candidate = VisualCorpus(CORPUS_DIR)
        return candidate if candidate.page_count else None
    return None


class ColPaliEngine:
    id = "colpali"
    SUPPORTS: set[str] = {"summary", "qa"} if _AVAILABLE else set()
    _import_error = _IMPORT_ERROR

    def __init__(
        self,
        cache: IndexCache,
        llm: LLMProvider,
        embedding_config: EmbeddingConfig | None = None,
        backend: ColPaliBackend | None = None,
        dpi: int = 150,
    ) -> None:
        self._cache = cache
        self._llm = llm
        # Accepted for construction symmetry with the text engines and
        # intentionally unused — see docstring point 2.
        self._embed = embedding_config
        self._backend = backend or TransformersColPaliBackend()
        self._dpi = dpi

    async def _build_index(self, corpus: Any) -> list[tuple[Any, Any]]:
        """Embed every page. Returns [(PageRef, patch_embeddings)]."""
        loop = asyncio.get_running_loop()

        def _build() -> list[tuple[Any, Any]]:
            rendered = corpus.render_pages()
            if not rendered:
                return []
            refs = [ref for ref, _ in rendered]
            embeddings = self._backend.embed_pages([png for _, png in rendered])
            return list(zip(refs, embeddings))

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
        resolved = _resolve_corpus(corpus)
        if resolved is None:
            return EngineResult(
                answer=_TEXT_ONLY if document_content.strip() else _NO_PAGES,
                retrieved_spans=(),
                retrieval_latency_ms=0,
                generation_latency_ms=0,
            )

        # dpi belongs in the key: the same corpus rendered at another
        # resolution is a different index. chunk_size/overlap do not — the
        # page is the chunk — so their slots carry dpi and a constant.
        key = (
            self.id,
            self._backend.model_id,
            self._dpi,
            0,
            resolved.version_hash,
        )
        cache_hit = self._cache.has(key)
        emitter.emit("ingest_start")
        index = await self._cache.get_or_build(key, lambda: self._build_index(resolved))
        emitter.emit("ingest_done", cache_hit=cache_hit)

        if not index:
            return EngineResult(
                answer=_NO_PAGES,
                retrieved_spans=(),
                retrieval_latency_ms=0,
                generation_latency_ms=0,
            )

        top_k = getattr(pill, "top_k", 3)
        query = f"{task} {goal}"

        emitter.emit("retrieval_start")
        t0 = time.perf_counter()
        loop = asyncio.get_running_loop()
        query_embedding = await loop.run_in_executor(
            None, lambda: self._backend.embed_query(query)
        )
        scored = sorted(
            ((maxsim(query_embedding, page_emb), ref) for ref, page_emb in index),
            key=lambda pair: pair[0],
            reverse=True,
        )[:top_k]
        retrieval_latency_ms = int((time.perf_counter() - t0) * 1000)
        emitter.emit("retrieval_done", took_ms=retrieval_latency_ms)

        # No locate_span() here: a PageRef already carries its exact interval
        # in the parent document, so there is nothing to recover by string
        # search and `unlocated_span_count` is structurally always 0.
        spans = tuple(
            RetrievedSpan(
                source_doc_id=ref.doc_id,
                char_start=ref.char_start,
                char_end=ref.char_end,
                text=ref.text,
                score=score,
                rank=rank,
            )
            for rank, (score, ref) in enumerate(scored)
        )

        context = "\n\n---\n\n".join(ref.text for _, ref in scored)
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
