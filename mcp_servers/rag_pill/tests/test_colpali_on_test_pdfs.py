"""ColPali against the real test corpus in test/pdfs/.

The other ColPali tests use a PDF built on the fly with three lines of text.
These run the same machinery over documents that look like what the arena
would actually be asked about: a ruled table, a bar chart, a labelled
diagram, a two-column form, and a scan.

The assertion that matters most is `test_scanned_document_is_invisible_to_
text_extraction`. It demonstrates, without any model weights, the exact gap
ColPali exists to fill: a text engine indexing that document gets *nothing*,
while the pages render to perfectly readable images. Whatever ColPali's
retrieval quality turns out to be, its score on that document cannot be
worse than zero, and every text engine's is exactly zero.

Build the corpus with:

    python scripts/build_test_pdfs.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mcp_servers.rag_pill.cache import IndexCache
from mcp_servers.rag_pill.corpus.visual import VisualCorpus
from mcp_servers.rag_pill.engines.colpali_engine import ColPaliEngine
from mcp_servers.rag_pill.schemas import QAPill

pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF not installed")

pytestmark = pytest.mark.anyio

PDF_DIR = Path(__file__).resolve().parents[3] / "test" / "pdfs"

EXPECTED_DOCUMENTS = {
    "formulaire_adhesion.pdf": 1,
    "notice_technique.pdf": 2,
    "rapport_scanne.pdf": 2,
    "rapport_trimestriel.pdf": 2,
}


@pytest.fixture(scope="module")
def corpus() -> VisualCorpus:
    if not PDF_DIR.exists() or not any(PDF_DIR.glob("*.pdf")):
        pytest.skip(f"{PDF_DIR} is empty — run scripts/build_test_pdfs.py")
    return VisualCorpus(PDF_DIR)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class SequentialBackend:
    """Ranks pages by a caller-chosen index, ignoring the pixels.

    Retrieval *quality* needs real weights; what these tests pin is that the
    plumbing survives real documents — every page gets embedded once, the
    winner's span resolves, and its text reaches the LLM.
    """

    model_id = "fake/sequential"

    def __init__(self, winner: int) -> None:
        self._winner = winner
        self.page_count = 0

    def embed_pages(self, images):
        self.page_count = len(images)
        return [np.eye(len(images))[i : i + 1] for i in range(len(images))]

    def embed_query(self, query: str):
        return np.eye(self.page_count)[self._winner : self._winner + 1]


class RecordingLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def invoke(self, pill, prompt: str) -> str:
        self.prompts.append(prompt)
        return "stub-answer"


def test_corpus_loads_every_document_and_page(corpus) -> None:
    found = {doc.id: doc.meta["page_count"] for doc in corpus.iter_documents()}
    assert found == EXPECTED_DOCUMENTS
    assert corpus.page_count == sum(EXPECTED_DOCUMENTS.values())


def test_every_page_span_round_trips_on_real_documents(corpus) -> None:
    for page in corpus.iter_pages():
        document = corpus.get_document(page.doc_id)
        assert document.text[page.char_start : page.char_end] == page.text, (
            f"span drift on {page.page_id}"
        )


def test_scanned_document_is_invisible_to_text_extraction(corpus) -> None:
    """The control case — and the whole argument for a visual engine."""
    scanned = [p for p in corpus.iter_pages() if p.doc_id == "rapport_scanne.pdf"]
    assert len(scanned) == 2

    for page in scanned:
        assert page.text.strip() == "", (
            f"{page.page_id} unexpectedly yielded text: {page.text[:120]!r}"
        )

    # ...yet the same pages render to substantial images. Nothing is missing
    # from the document; it is missing only from the text layer.
    rendered = {
        ref.page_id: png
        for ref, png in VisualCorpus(PDF_DIR).render_pages()
        if ref.doc_id == "rapport_scanne.pdf"
    }
    assert len(rendered) == 2
    for page_id, png in rendered.items():
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(png) > 50_000, f"{page_id} rendered suspiciously small"


def test_table_and_diagram_pages_keep_their_values_in_the_text_layer(corpus) -> None:
    """Counterpart to the scan: where extraction *does* work, the numbers
    survive — so a page ColPali picks can actually be answered from."""
    pages = {p.page_id: p.text for p in corpus.iter_pages()}

    table_page = pages["rapport_trimestriel.pdf#p0"]
    assert "Sud" in table_page
    assert "2110" in table_page  # the T3 cell that crosses 2 000

    specs_page = pages["notice_technique.pdf#p0"]
    assert "IP44" in specs_page
    assert "Purgeur" in specs_page


async def test_engine_runs_end_to_end_over_the_real_corpus(corpus) -> None:
    pages = list(corpus.iter_pages())
    winner = next(
        i for i, p in enumerate(pages) if p.page_id == "rapport_trimestriel.pdf#p0"
    )
    backend = SequentialBackend(winner)
    llm = RecordingLLM()
    engine = ColPaliEngine(IndexCache(max_entries=2), llm=llm, backend=backend)

    result = await engine.execute_with_spans(
        QAPill(name="t", task_type="qa", top_k=1),
        "Quel est le chiffre d'affaires de la région Sud au troisième trimestre ?",
        "",
        corpus=corpus,
    )

    assert backend.page_count == corpus.page_count, "every page must be embedded once"
    assert len(result.retrieved_spans) == 1
    span = result.retrieved_spans[0]
    assert span.source_doc_id == "rapport_trimestriel.pdf"
    assert result.unlocated_span_count == 0

    # The retrieved page's own numbers reach the LLM, so the answer is
    # actually derivable from what retrieval handed over.
    assert len(llm.prompts) == 1
    assert "2110" in llm.prompts[0]
    assert result.answer == "stub-answer"


async def test_retrieving_a_scanned_page_hands_the_llm_nothing(corpus) -> None:
    """Honest failure mode, pinned: ColPali can *find* a scanned page, but
    this engine passes page text to the LLM, and a scan has none. Reading
    the pixels needs a vision-capable generation step — out of scope while
    the arena fixes one text LLM for every contestant."""
    pages = list(corpus.iter_pages())
    winner = next(i for i, p in enumerate(pages) if p.doc_id == "rapport_scanne.pdf")
    llm = RecordingLLM()
    engine = ColPaliEngine(
        IndexCache(max_entries=2), llm=llm, backend=SequentialBackend(winner)
    )

    result = await engine.execute_with_spans(
        QAPill(name="t", task_type="qa", top_k=1), "turbine", "", corpus=corpus
    )

    assert result.retrieved_spans[0].source_doc_id == "rapport_scanne.pdf"
    assert result.retrieved_spans[0].text.strip() == ""
