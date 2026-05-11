"""ToolVoteRecord — Phase 13 fields for benchmark/sandbox + judgement.

Wave 4 / 4.8 + 4.9: ToolVoteRecord carries haystack_mode + evaluation_query_id
so vote analytics can split benchmark scoring from sandbox votes. Wave 5
populates judgement_a / judgement_b with the JudgementScore JSON.

Tests pin the field defaults so legacy callers that don't supply Phase 13
fields keep working — additive contract.
"""

from backend.tool_arena.persistence import ToolVoteRecord


def _base_kwargs() -> dict:
    return dict(
        session_hash="abc",
        tool_a_id="srv-a",
        tool_b_id="srv-b",
        chosen="a",
        llm_id="model-x",
        task="Quelle est la capitale ?",
        goal="Réponse précise.",
        timestamp="2026-05-11T00:00:00Z",
    )


def test_tool_vote_record_defaults_haystack_mode_and_eval_id() -> None:
    """Slice 4.8 — legacy ToolVoteRecord without Phase 13 fields gets
    haystack_mode='sandbox' and evaluation_query_id=None by default."""
    record = ToolVoteRecord(**_base_kwargs())
    assert record.haystack_mode == "sandbox"
    assert record.evaluation_query_id is None
    assert record.judgement_a is None
    assert record.judgement_b is None


def test_tool_vote_record_accepts_benchmark_fields() -> None:
    """Benchmark vote: haystack_mode + evaluation_query_id + judgements
    survive round-trip through Pydantic."""
    record = ToolVoteRecord(
        **_base_kwargs(),
        haystack_mode="benchmark",
        evaluation_query_id="q01_capital_france",
        judgement_a={"contains_gold": True, "mrr": 1.0},
        judgement_b={"contains_gold": False, "mrr": 0.0},
    )
    assert record.haystack_mode == "benchmark"
    assert record.evaluation_query_id == "q01_capital_france"
    assert record.judgement_a == {"contains_gold": True, "mrr": 1.0}
    assert record.judgement_b == {"contains_gold": False, "mrr": 0.0}


def test_tool_vote_record_dump_preserves_phase13_columns() -> None:
    """Slice 4.9 (data shape) — model_dump emits the columns that the
    additive 006 migration adds; save_tool_vote_to_db's parameterized
    INSERT picks them up automatically via the (fields, values) helper."""
    record = ToolVoteRecord(
        **_base_kwargs(),
        haystack_mode="benchmark",
        evaluation_query_id="q01",
    )
    dumped = record.model_dump(mode="json")
    assert "haystack_mode" in dumped and dumped["haystack_mode"] == "benchmark"
    assert "evaluation_query_id" in dumped and dumped["evaluation_query_id"] == "q01"
    assert "judgement_a" in dumped and dumped["judgement_a"] is None
    assert "judgement_b" in dumped and dumped["judgement_b"] is None
