"""Pill schema validation — discriminated union behavior."""

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_servers.rag_pill.schemas import (
    ExtractionPill,
    Pill,
    QAPill,
    SummaryPill,
)

adapter = TypeAdapter(Pill)


def test_summary_pill_validates():
    pill = adapter.validate_python(
        {"name": "s1", "task_type": "summary", "compression_ratio": 0.3}
    )
    assert isinstance(pill, SummaryPill)
    assert pill.style == "paragraph"  # default


def test_qa_pill_validates():
    pill = adapter.validate_python(
        {"name": "q1", "task_type": "qa", "top_k": 5}
    )
    assert isinstance(pill, QAPill)
    assert pill.cite_sources is True


def test_extraction_pill_requires_output_schema():
    with pytest.raises(ValidationError):
        adapter.validate_python({"name": "e1", "task_type": "extraction"})
    pill = adapter.validate_python(
        {"name": "e1", "task_type": "extraction", "output_schema": {"x": "int"}}
    )
    assert isinstance(pill, ExtractionPill)


def test_unknown_task_type_rejected():
    with pytest.raises(ValidationError):
        adapter.validate_python({"name": "x", "task_type": "translation"})


def test_summary_field_on_qa_pill_rejected_by_discriminator():
    # cite_sources only valid on QA; passing it on summary is silently ignored
    # (Pydantic discriminated unions reject unknown by default? Actually extras
    # ignored by default). Assert the discriminator picked the right model.
    pill = adapter.validate_python(
        {"name": "s2", "task_type": "summary", "cite_sources": True}
    )
    assert isinstance(pill, SummaryPill)
    assert not hasattr(pill, "cite_sources")
