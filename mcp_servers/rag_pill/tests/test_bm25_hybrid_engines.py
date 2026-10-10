"""BM25 and hybrid engines — and the case for adding them.

The first three tests are the argument. BM25 and a dense retriever fail on
*opposite* inputs: BM25 cannot match a synonym, a dense model smooths away
a rare exact token. Each test puts one of them in the situation that breaks
it, and shows the hybrid recovering both.

The dense half is faked, deliberately and visibly: a two-topic bag of words
that knows nothing about part numbers. That is not a strawman — it is the
documented failure mode of dense retrieval on rare identifiers, reproduced
in a form a test can pin.
"""

from __future__ import annotations

import numpy as np
import pytest

from mcp_servers.rag_pill.cache import IndexCache
from mcp_servers.rag_pill.corpus.base import CorpusDocument, compute_version_hash
from mcp_servers.rag_pill.engines.bm25_engine import BM25Engine
from mcp_servers.rag_pill.engines.hybrid_engine import HybridEngine
from mcp_servers.rag_pill.engines.lexical import tokenize
from mcp_servers.rag_pill.providers import EmbeddingConfig
from mcp_servers.rag_pill.schemas import QAPill

pytestmark = pytest.mark.anyio

HYDRAULIC = "La pompe de circulation est entrainee par un moteur electrique."
PART_NUMBER = "La piece de rechange porte la reference PAL-3300-B en magasin."
ADMIN = "Le formulaire d'adhesion exige une cotisation et un numero de dossier."

DOCUMENTS = (HYDRAULIC, PART_NUMBER, ADMIN)

# A two-topic "embedding" vocabulary. Note what is absent: every token of
# PAL-3300-B. A dense model trained on prose treats such an identifier as
# near-noise, and this fake reproduces that exactly.
TOPICS = (
    ("pompe", "circulation", "moteur", "electrique", "hydraulique", "debit"),
    ("formulaire", "adhesion", "cotisation", "dossier", "administratif"),
)


def fake_embed(texts: list[str]) -> np.ndarray:
    rows = []
    for text in texts:
        tokens = tokenize(text)
        rows.append([float(sum(t in topic for t in tokens)) for topic in TOPICS])
    return np.array(rows, dtype=np.float32)


class TinyCorpus:
    """One sentence per document, so a chunk index equals a document index."""

    id = "tiny"
    has_ground_truth = False

    def __init__(self, texts=DOCUMENTS) -> None:
        self._docs = [
            CorpusDocument(id=f"doc{i}.md", text=t) for i, t in enumerate(texts)
        ]

    def iter_documents(self):
        return iter(self._docs)

    def get_document(self, doc_id):
        return next((d for d in self._docs if d.id == doc_id), None)

    @property
    def version_hash(self) -> str:
        return compute_version_hash(self._docs)


class RecordingLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def invoke(self, pill, prompt: str) -> str:
        self.prompts.append(prompt)
        return "stub-answer"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def corpus() -> TinyCorpus:
    return TinyCorpus()


def _pill(top_k: int = 1) -> QAPill:
    # chunk_size comfortably exceeds every sentence, so one document is one
    # chunk and span assertions stay readable.
    return QAPill(name="t", task_type="qa", top_k=top_k, chunk_size=500, chunk_overlap=0)


def _bm25(llm) -> BM25Engine:
    return BM25Engine(IndexCache(max_entries=4), llm=llm)


def _hybrid(llm) -> HybridEngine:
    return HybridEngine(
        IndexCache(max_entries=4),
        llm=llm,
        embedding_config=EmbeddingConfig(api_key="unused"),
        embed_fn=fake_embed,
    )


def _dense_only_ranking(query: str) -> list[str]:
    matrix = fake_embed(list(DOCUMENTS))
    from mcp_servers.rag_pill.engines.hybrid_engine import cosine_ranking

    return [
        DOCUMENTS[i] for i in cosine_ranking(fake_embed([query])[0], matrix, pool=3)
    ]


async def test_bm25_finds_the_exact_identifier_that_dense_retrieval_misses(
    corpus,
) -> None:
    """The case for a lexical engine, in one assertion."""
    llm = RecordingLLM()
    result = await _bm25(llm).execute_with_spans(_pill(), "PAL-3300-B", "", corpus=corpus)

    assert result.retrieved_spans[0].text == PART_NUMBER

    # ...and the dense retriever, on the same query, does not put it first.
    assert _dense_only_ranking("PAL-3300-B")[0] != PART_NUMBER


async def test_bm25_is_blind_to_a_synonym_that_dense_retrieval_catches(corpus) -> None:
    """The mirror case — the reason BM25 is a floor and not a replacement.

    'equipement hydraulique' shares no token with any document, so BM25 has
    nothing to match at all.
    """
    llm = RecordingLLM()
    result = await _bm25(llm).execute_with_spans(
        _pill(), "equipement hydraulique", "", corpus=corpus
    )

    assert result.retrieved_spans == (), "BM25 unexpectedly matched a synonym"
    assert _dense_only_ranking("equipement hydraulique")[0] == HYDRAULIC


@pytest.mark.parametrize(
    "query,expected",
    [
        ("PAL-3300-B", PART_NUMBER),           # only BM25 finds it
        ("equipement hydraulique", HYDRAULIC),  # only the dense half finds it
    ],
)
async def test_hybrid_recovers_both_failure_modes(corpus, query, expected) -> None:
    """The payoff: one engine that answers both of the previous two tests."""
    llm = RecordingLLM()
    result = await _hybrid(llm).execute_with_spans(_pill(), query, "", corpus=corpus)

    assert result.retrieved_spans[0].text == expected


async def test_bm25_runs_with_no_embedding_provider_whatsoever(corpus) -> None:
    """Zero API cost is half the reason this engine is the control.

    Constructed with no EmbeddingConfig at all: if any code path reached for
    an embedder, it would raise on None rather than quietly billing a call.
    Retrieval still succeeds, which is the proof.
    """
    engine = BM25Engine(IndexCache(max_entries=2), llm=RecordingLLM())
    assert engine._embed is None

    result = await engine.execute_with_spans(
        _pill(), "PAL-3300-B", "", corpus=corpus
    )
    assert result.retrieved_spans[0].text == PART_NUMBER


@pytest.mark.parametrize("engine_factory", [_bm25, _hybrid], ids=["bm25", "hybrid"])
async def test_spans_are_exact_and_never_unlocated(corpus, engine_factory) -> None:
    llm = RecordingLLM()
    result = await engine_factory(llm).execute_with_spans(
        _pill(top_k=2), "pompe moteur", "", corpus=corpus
    )

    assert result.retrieved_spans
    for span in result.retrieved_spans:
        document = corpus.get_document(span.source_doc_id)
        assert document.text[span.char_start : span.char_end] == span.text
    assert result.unlocated_span_count == 0


@pytest.mark.parametrize("engine_factory", [_bm25, _hybrid], ids=["bm25", "hybrid"])
async def test_retrieved_text_reaches_the_shared_llm_once(corpus, engine_factory) -> None:
    llm = RecordingLLM()
    await engine_factory(llm).execute_with_spans(
        _pill(), "PAL-3300-B", "", corpus=corpus
    )
    assert len(llm.prompts) == 1
    assert "PAL-3300-B" in llm.prompts[0]


@pytest.mark.parametrize("engine_factory", [_bm25, _hybrid], ids=["bm25", "hybrid"])
async def test_progress_events_follow_the_shared_sequence(corpus, engine_factory) -> None:
    seen: list[str] = []

    class Emitter:
        def emit(self, type: str, **payload) -> None:
            seen.append(type)

    await engine_factory(RecordingLLM()).execute_with_spans(
        _pill(), "pompe", "", corpus=corpus, progress=Emitter()
    )
    assert seen == [
        "ingest_start",
        "ingest_done",
        "retrieval_start",
        "retrieval_done",
        "mediation_start",
        "mediation_done",
    ]


@pytest.mark.parametrize("engine_factory", [_bm25, _hybrid], ids=["bm25", "hybrid"])
async def test_index_is_cached_across_queries(corpus, engine_factory) -> None:
    llm = RecordingLLM()
    engine = engine_factory(llm)
    first = await engine.execute_with_spans(_pill(), "pompe", "", corpus=corpus)
    second = await engine.execute_with_spans(_pill(), "pompe", "", corpus=corpus)
    assert first.retrieved_spans == second.retrieved_spans


@pytest.mark.parametrize("engine_factory", [_bm25, _hybrid], ids=["bm25", "hybrid"])
async def test_no_corpus_is_reported_not_crashed(engine_factory) -> None:
    llm = RecordingLLM()
    result = await engine_factory(llm).execute_with_spans(
        _pill(), "pompe", "", corpus=TinyCorpus(texts=())
    )
    assert result.retrieved_spans == ()
