"""CompareRequest mode validator — Phase 13 benchmark/sandbox discriminator.

Wave 4 / 4.4 + 4.5 + 4.6: enforce the haystack-mode XOR at the boundary so
the router never has to defensively handle inconsistent body shapes.

Tests use Pydantic ValidationError to assert the validator rejects bad
inputs without reaching the dispatcher.
"""

import pytest
from pydantic import ValidationError

from backend.tool_arena.comparison.contracts import CompareRequest


def test_sandbox_with_document_content_accepted() -> None:
    """Happy path: existing sandbox callers (the common case) keep working
    without specifying haystack=sandbox explicitly — it's the default."""
    req = CompareRequest(task="t", goal="g", document_content="hello")
    assert req.haystack == "sandbox"
    assert req.evaluation_query_id is None


def test_benchmark_mode_with_evaluation_query_id_accepted() -> None:
    """Benchmark mode: evaluation_query_id supplied, document_content
    optional (rag_pill resolves the corpus from the fixed catalog)."""
    req = CompareRequest(
        task="",
        goal="",
        haystack="benchmark",
        evaluation_query_id="q01_capital_france",
    )
    assert req.haystack == "benchmark"
    assert req.evaluation_query_id == "q01_capital_france"


def test_benchmark_without_evaluation_query_id_rejected() -> None:
    """Slice 4.4 — benchmark mode requires evaluation_query_id (the router
    needs it to look up task/goal substitution)."""
    with pytest.raises(ValidationError, match="evaluation_query_id"):
        CompareRequest(task="t", goal="g", haystack="benchmark")


def test_sandbox_without_document_content_rejected() -> None:
    """Slice 4.5 — sandbox mode requires non-empty document_content
    (otherwise rag_pill engines fall through to FixedCorpus, which is the
    benchmark haystack — silent mode confusion)."""
    with pytest.raises(ValidationError, match="document_content"):
        CompareRequest(task="t", goal="g", haystack="sandbox", document_content="")


def test_sandbox_with_evaluation_query_id_rejected() -> None:
    """Slice 4.6 — XOR: evaluation_query_id is only valid in benchmark mode.
    Catches sandbox callers who accidentally include a stale eval id."""
    with pytest.raises(ValidationError, match="benchmark"):
        CompareRequest(
            task="t",
            goal="g",
            document_content="hi",
            haystack="sandbox",
            evaluation_query_id="q01_capital_france",
        )


def test_legacy_no_haystack_field_defaults_to_sandbox() -> None:
    """Back-compat: clients written before Phase 13 don't send `haystack`.
    Default to sandbox; behaves exactly like pre-Phase-13."""
    req = CompareRequest(task="t", goal="g", document_content="ok")
    assert req.haystack == "sandbox"
