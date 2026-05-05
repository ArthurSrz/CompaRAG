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
    assert "25%" in out
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
