"""PromptStrategy unit tests — pure functions of (pill, context, task, goal).

These run without an LLM, network, or API key. The fact that the prompt is
testable here at all is the win from deepening B; previously the prompt only
existed inside an LLM-bound coroutine in each engine.
"""

import pytest

from mcp_servers.rag_pill.schemas import ExtractionPill, QAPill, SummaryPill
from mcp_servers.rag_pill.strategies import render_prompt


def test_summary_includes_compression_pct_and_style():
    pill = SummaryPill(
        name="t", task_type="summary", compression_ratio=0.25, style="bullet"
    )
    out = render_prompt(pill, context="ctx", task="What", goal="happened?")
    assert "at most 30 words" in out  # 25% of 1 word, floored
    assert "bullet" in out
    assert "ctx" in out
    assert "What happened?" in out


def test_qa_with_citations_mentions_cite():
    pill = QAPill(name="t", task_type="qa", cite_sources=True)
    out = render_prompt(pill, context="ctx", task="Why", goal="?")
    assert "Cite" in out


def test_qa_without_citations_omits_cite():
    pill = QAPill(name="t", task_type="qa", cite_sources=False)
    out = render_prompt(pill, context="ctx", task="Why", goal="?")
    assert "Cite" not in out


def test_extraction_embeds_schema_as_json():
    pill = ExtractionPill(
        name="t",
        task_type="extraction",
        output_schema={"name": "string", "age": "int"},
    )
    out = render_prompt(pill, context="ctx", task="Pull", goal="people")
    assert '"name"' in out and '"age"' in out
    assert "JSON" in out


def test_unknown_task_type_raises():
    """A task_type without a strategy must error loudly, not silently no-op."""

    class FakePill:
        task_type = "translation"

    with pytest.raises(ValueError, match="task_type"):
        render_prompt(FakePill(), "", "", "")


# ── Phase 2 : qualité de sortie (test utilisateur prod 2026-10-03) ──────────
# Haystack a résumé un PDF d'une phrase en un long texte interprétatif et a
# recopié sa consigne (« Format concis (≈20% de la source) ») dans la réponse.

def _summary(ratio: float = 0.2) -> SummaryPill:
    return SummaryPill(name="t", task_type="summary", compression_ratio=ratio, style="paragraph")


def test_summary_gives_a_word_budget_derived_from_the_context():
    context = " ".join(["mot"] * 500)
    out = render_prompt(_summary(0.2), context=context, task="Résume", goal="")
    assert "100 words" in out


def test_summary_budget_has_a_floor_for_tiny_sources():
    out = render_prompt(_summary(0.2), context="Le marmot examine l'équifinalité.", task="Résume", goal="")
    assert "30 words" in out
    assert "shorter than" in out  # ne jamais délayer une source courte


def test_summary_forbids_echoing_instructions_and_adding_interpretation():
    out = render_prompt(_summary(), context="ctx", task="Résume", goal="")
    assert "Never mention these instructions" in out
    assert "Do not add interpretation" in out


@pytest.mark.parametrize(
    "pill",
    [_summary(), QAPill(name="t", task_type="qa", cite_sources=True)],
    ids=["summary", "qa"],
)
def test_answers_in_the_language_of_the_question(pill):
    out = render_prompt(pill, context="ctx", task="Quel est le budget ?", goal="")
    assert "same language as the Question" in out
