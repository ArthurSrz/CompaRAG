"""ColPaliEngine — behaviour with a deterministic fake visual encoder.

The real encoder is a multi-gigabyte VLM, so these tests inject a fake
through the ColPaliBackend Protocol. That is the point of the Protocol:
everything the arena depends on — which page wins, what span is reported,
which prompt reaches the LLM, that the shared LLM is used at all — is
engine logic, not model weights, and must be testable without them.

What is NOT covered here: retrieval *quality* (does ColPali actually rank
the right page?) and latency. Both need real weights and belong in a smoke
run against `vidore/colSmol-256M`.
"""

from __future__ import annotations

import numpy as np
import pytest

from mcp_servers.rag_pill.cache import IndexCache
from mcp_servers.rag_pill.corpus.visual import VisualCorpus
from mcp_servers.rag_pill.engines.colpali_engine import ColPaliEngine
from mcp_servers.rag_pill.schemas import QAPill

pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF not installed")

pytestmark = pytest.mark.anyio


PAGE_TEXTS = (
    "Alpha page about marmots and their burrows.",
    "Beta page about glaciers and moraine deposits.",
    "Gamma page about lichen growth on north faces.",
)

# One-hot per page, so the fake query embedding selects a winner by index.
PAGE_VECTORS = [np.eye(3)[i : i + 1] for i in range(3)]


class FakeBackend:
    """Returns preset embeddings in corpus page order.

    Deliberately ignores the pixels: the engine's contract is that it asks
    for every rendered page once, in order, and ranks by MaxSim over what
    comes back. Asserting on `pages_seen` pins that contract.
    """

    model_id = "fake/colpali-test"

    def __init__(self, winner_index: int) -> None:
        self._winner = winner_index
        self.pages_seen = 0
        self.queries_seen: list[str] = []

    def embed_pages(self, images):
        self.pages_seen += len(images)
        assert len(images) == len(PAGE_VECTORS), "engine must embed every page once"
        return list(PAGE_VECTORS)

    def embed_query(self, query: str):
        self.queries_seen.append(query)
        return np.eye(3)[self._winner : self._winner + 1]


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
def corpus(tmp_path) -> VisualCorpus:
    doc = pymupdf.open()
    for text in PAGE_TEXTS:
        doc.new_page().insert_text((72, 72), text)
    doc.save(tmp_path / "alpine.pdf")
    doc.close()
    return VisualCorpus(tmp_path)


def _pill(top_k: int = 1) -> QAPill:
    return QAPill(name="colpali_test", task_type="qa", top_k=top_k)


def _engine(winner: int, llm: RecordingLLM) -> tuple[ColPaliEngine, FakeBackend]:
    backend = FakeBackend(winner)
    engine = ColPaliEngine(IndexCache(max_entries=4), llm=llm, backend=backend)
    return engine, backend


@pytest.mark.parametrize("winner", [0, 1, 2])
async def test_retrieved_span_points_at_the_winning_page(corpus, winner) -> None:
    """The span must address the winning page's exact interval in the doc.

    This is the assertion that makes ColPali comparable to the text engines:
    the judge scores `[char_start, char_end)` against ground truth, so a
    visually-retrieved page has to resolve to the same coordinate system.
    """
    llm = RecordingLLM()
    engine, _ = _engine(winner, llm)

    result = await engine.execute_with_spans(
        _pill(), "Where do marmots live?", "", corpus=corpus
    )

    assert len(result.retrieved_spans) == 1
    span = result.retrieved_spans[0]
    expected_page = list(corpus.iter_pages())[winner]

    assert span.source_doc_id == "alpine.pdf"
    assert (span.char_start, span.char_end) == (
        expected_page.char_start,
        expected_page.char_end,
    )
    document = corpus.get_document("alpine.pdf")
    assert document.text[span.char_start : span.char_end] == expected_page.text
    # Exact by construction — never recovered by str.find(), so never unlocated.
    assert result.unlocated_span_count == 0


async def test_top_k_controls_how_many_pages_are_returned(corpus) -> None:
    llm = RecordingLLM()
    engine, _ = _engine(winner=1, llm=llm)

    result = await engine.execute_with_spans(
        _pill(top_k=2), "glaciers", "", corpus=corpus
    )

    assert len(result.retrieved_spans) == 2
    assert [s.rank for s in result.retrieved_spans] == [0, 1]
    # Ranked by descending score.
    scores = [s.score for s in result.retrieved_spans]
    assert scores == sorted(scores, reverse=True)


async def test_winning_page_text_reaches_the_shared_llm(corpus) -> None:
    """LLM parity: ColPali retrieves on pixels, then generates through the
    same LLMProvider on the page's text — exactly one call, like every
    other engine."""
    llm = RecordingLLM()
    engine, backend = _engine(winner=2, llm=llm)

    answer = await engine.execute(_pill(), "lichen", "", corpus=corpus)

    assert answer == "stub-answer"
    assert len(llm.prompts) == 1
    assert "lichen" in llm.prompts[0]
    assert backend.queries_seen == ["lichen "]


async def test_index_is_built_once_and_cached(corpus) -> None:
    llm = RecordingLLM()
    engine, backend = _engine(winner=0, llm=llm)

    await engine.execute_with_spans(_pill(), "marmots", "", corpus=corpus)
    await engine.execute_with_spans(_pill(), "burrows", "", corpus=corpus)

    assert backend.pages_seen == len(PAGE_TEXTS), "pages re-embedded on second query"


async def test_text_only_upload_is_refused_with_an_explanation(corpus) -> None:
    """A flattened upload has no pixels. Say so rather than silently
    returning an empty answer the voter cannot interpret."""
    llm = RecordingLLM()
    engine, _ = _engine(winner=0, llm=llm)

    result = await engine.execute_with_spans(
        _pill(), "marmots", "", document_content="some extracted text", corpus=None
    )

    assert "flattened" in result.answer
    assert result.retrieved_spans == ()
    assert llm.prompts == []


async def test_corpus_without_pages_is_refused(tmp_path) -> None:
    llm = RecordingLLM()
    engine, _ = _engine(winner=0, llm=llm)

    result = await engine.execute_with_spans(
        _pill(), "marmots", "", corpus=VisualCorpus(tmp_path)
    )

    assert "No page images" in result.answer
    assert llm.prompts == []


async def test_progress_events_follow_the_shared_sequence(corpus) -> None:
    """The frontend ProgressCard keys off these event names; a visual engine
    must not invent its own vocabulary."""
    llm = RecordingLLM()
    engine, _ = _engine(winner=0, llm=llm)
    seen: list[str] = []

    class Emitter:
        def emit(self, type: str, **payload) -> None:
            seen.append(type)

    await engine.execute_with_spans(
        _pill(), "marmots", "", corpus=corpus, progress=Emitter()
    )

    assert seen == [
        "ingest_start",
        "ingest_done",
        "retrieval_start",
        "retrieval_done",
        "mediation_start",
        "mediation_done",
    ]
