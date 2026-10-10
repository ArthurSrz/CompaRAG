"""VisualCorpus — pages must carry exact character intervals.

The whole point of VisualCorpus is that a visual retriever stays scoreable
on the arena's char-interval scale. These tests pin that invariant: for
every page, `document.text[page.char_start:page.char_end]` must be that
page's own text, byte for byte. If this drifts, ColPali's Recall@K silently
stops meaning the same thing as LangChain's.
"""

from __future__ import annotations

import pytest

from mcp_servers.rag_pill.corpus.visual import VisualCorpus

pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF not installed")


PAGE_TEXTS = (
    "Alpha page about marmots and their burrows.",
    "Beta page about glaciers and moraine deposits.",
    "Gamma page about lichen growth on north faces.",
)


@pytest.fixture
def corpus_root(tmp_path):
    doc = pymupdf.open()
    for text in PAGE_TEXTS:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(tmp_path / "alpine.pdf")
    doc.close()
    return tmp_path


def test_every_page_span_round_trips_to_its_own_text(corpus_root) -> None:
    corpus = VisualCorpus(corpus_root)
    document = corpus.get_document("alpine.pdf")
    assert document is not None

    pages = list(corpus.iter_pages())
    assert len(pages) == len(PAGE_TEXTS)

    for page in pages:
        sliced = document.text[page.char_start : page.char_end]
        assert sliced == page.text, (
            f"page {page.page_number} span [{page.char_start},{page.char_end}) "
            f"sliced {sliced!r} but page text is {page.text!r}"
        )


def test_page_order_and_identity(corpus_root) -> None:
    pages = list(VisualCorpus(corpus_root).iter_pages())
    assert [p.page_number for p in pages] == [0, 1, 2]
    assert [p.page_id for p in pages] == [
        "alpine.pdf#p0",
        "alpine.pdf#p1",
        "alpine.pdf#p2",
    ]
    # Tracer words survive extraction and land on the right page.
    assert "marmots" in pages[0].text
    assert "glaciers" in pages[1].text
    assert "lichen" in pages[2].text


def test_document_text_is_pages_joined_by_separator(corpus_root) -> None:
    corpus = VisualCorpus(corpus_root)
    document = corpus.get_document("alpine.pdf")
    pages = list(corpus.iter_pages())
    assert document.text == VisualCorpus.PAGE_SEPARATOR.join(p.text for p in pages)
    assert document.meta["page_count"] == len(PAGE_TEXTS)


def test_render_pages_returns_png_bytes_in_page_order(corpus_root) -> None:
    rendered = VisualCorpus(corpus_root).render_pages()
    assert [ref.page_number for ref, _ in rendered] == [0, 1, 2]
    for _, png in rendered:
        assert png.startswith(b"\x89PNG\r\n\x1a\n"), "not a PNG payload"


def test_version_hash_is_stable_and_content_sensitive(corpus_root, tmp_path) -> None:
    first = VisualCorpus(corpus_root).version_hash
    assert first == VisualCorpus(corpus_root).version_hash

    other = tmp_path / "other"
    other.mkdir()
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "A different document entirely.")
    doc.save(other / "alpine.pdf")
    doc.close()
    assert VisualCorpus(other).version_hash != first


def test_empty_root_yields_no_pages(tmp_path) -> None:
    corpus = VisualCorpus(tmp_path)
    assert corpus.page_count == 0
    assert list(corpus.iter_documents()) == []
