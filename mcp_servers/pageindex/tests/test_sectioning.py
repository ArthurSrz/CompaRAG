"""Tests de ensure_sections — sans le package PageIndex vendored."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sectioning import ensure_sections  # noqa: E402

HEADER = re.compile(r"^#{1,6}\s+.+$", re.M)

RAG_TXT = (
    "Retrieval-augmented generation combines a parametric language model "
    "with a non-parametric retrieval system.\n\n"
    "The retrieval step typically uses dense vector embeddings.\n\n"
    "Faithfulness without correctness indicates hallucination; correctness "
    "without faithfulness indicates lucky guessing."
)


def _body(md: str) -> str:
    return re.sub(r"\s+", " ", HEADER.sub("", md)).strip()


def test_plain_text_gets_at_least_one_heading_and_keeps_all_text():
    out = ensure_sections(RAG_TXT)
    assert HEADER.search(out)
    assert _body(out) == re.sub(r"\s+", " ", RAG_TXT).strip()


def test_long_plain_text_is_split_near_target_size():
    para = "Une phrase de test assez longue pour remplir la section. " * 10
    text = "\n\n".join([para] * 12)
    out = ensure_sections(text, target_chars=2000)
    titles = HEADER.findall(out)
    assert 3 <= len(titles) <= 6
    for section in re.split(r"^# .+$", out, flags=re.M)[1:]:
        assert len(section.strip()) <= 2000


def test_pdf_like_text_without_blank_lines_is_still_split():
    text = "\n".join(f"Ligne {i} du document extrait d'un PDF." for i in range(300))
    out = ensure_sections(text, target_chars=1000)
    assert len(HEADER.findall(out)) > 5


def test_single_huge_paragraph_is_split_on_sentences():
    text = "Phrase numéro un du bloc. " * 400
    out = ensure_sections(text, target_chars=2000)
    assert len(HEADER.findall(out)) >= 5


def test_titles_use_first_words_of_the_section():
    out = ensure_sections(RAG_TXT)
    assert out.startswith("# Section 1 : Retrieval-augmented generation combines")


def test_structured_markdown_is_unchanged():
    md = "# Intro\n\nTexte.\n\n## Détail\n\nPlus de texte."
    assert ensure_sections(md) == md


def test_preamble_before_first_heading_is_kept():
    md = "Texte d'ouverture important.\n\n# Chapitre\n\nCorps."
    out = ensure_sections(md)
    assert out.startswith("# Préambule\n\nTexte d'ouverture important.")
    assert "# Chapitre" in out


def test_hash_inside_code_block_is_not_a_heading():
    md = "```\n# pas un titre\n```\nDu texte sans titre."
    out = ensure_sections(md)
    assert out.startswith("# Section 1")


def test_empty_text_is_returned_as_is():
    assert ensure_sections("   \n") == "   \n"
