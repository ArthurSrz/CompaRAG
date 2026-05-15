"""save_tool_vote_to_db threads judgement_a / judgement_b into the SQL INSERT.

Slice 5.11: the db() context manager builds `fields` and `values` strings
from data.keys(); Wave 4's ToolVoteRecord additions surface haystack_mode,
evaluation_query_id, judgement_a, judgement_b in model_dump — so the INSERT
picks them up automatically. This test pins the contract by capturing the
cursor's execute() args.
"""

from unittest.mock import MagicMock, patch

from backend.tool_arena.vote.save_vote_to_database import ToolVoteRecord, save_tool_vote_to_db


def test_save_tool_vote_to_db_writes_judgement_columns() -> None:
    """Slice 5.11 — judgement_a + judgement_b appear in the parameterized
    INSERT statement and in the bound params dict."""
    record = ToolVoteRecord(
        session_hash="sess-x",
        tool_a_id="srv-a",
        tool_b_id="srv-b",
        chosen="a",
        llm_id="stub",
        task="Quelle est la capitale ?",
        goal="Réponse précise.",
        timestamp="2026-05-11T00:00:00Z",
        haystack_mode="benchmark",
        evaluation_query_id="q01_capital_france",
        judgement_a={"contains_gold": True, "mrr": 1.0, "recall_at_k": {"1": 1.0}},
        judgement_b={"contains_gold": False, "mrr": 0.0, "recall_at_k": {"1": 0.0}},
    )
    payload = record.model_dump(mode="json")

    captured: dict = {}
    fake_cursor = MagicMock()

    def fake_execute(sql, params):
        captured["sql"] = sql
        captured["params"] = params

    fake_cursor.execute.side_effect = fake_execute

    from contextlib import contextmanager

    @contextmanager
    def fake_db_ctx(data, action):
        fields = ", ".join(data.keys())
        values = ", ".join(f"%({k})s" for k in data.keys())
        yield (fake_cursor, fields, values)

    with patch("backend.tool_arena.vote.save_vote_to_database.db", fake_db_ctx):
        save_tool_vote_to_db(payload)

    sql = captured["sql"]
    params = captured["params"]
    # New columns in the SQL field list:
    assert "haystack_mode" in sql
    assert "evaluation_query_id" in sql
    assert "judgement_a" in sql
    assert "judgement_b" in sql
    # And in the bound params with the right values:
    assert params["haystack_mode"] == "benchmark"
    assert params["evaluation_query_id"] == "q01_capital_france"
    assert params["judgement_a"] == {
        "contains_gold": True, "mrr": 1.0, "recall_at_k": {"1": 1.0},
    }
    assert params["judgement_b"]["contains_gold"] is False


def test_save_tool_vote_sandbox_writes_null_judgements() -> None:
    """Sandbox mode never scores. judgement_a/b are NULL in the INSERT;
    haystack_mode defaults to 'sandbox' even if not explicitly supplied."""
    record = ToolVoteRecord(
        session_hash="sess-x",
        tool_a_id="srv-a",
        tool_b_id="srv-b",
        chosen="tie",
        llm_id="stub",
        task="t",
        goal="g",
        timestamp="2026-05-11T00:00:00Z",
    )
    payload = record.model_dump(mode="json")

    captured: dict = {}
    fake_cursor = MagicMock()
    fake_cursor.execute.side_effect = lambda sql, params: captured.update(
        sql=sql, params=params
    )

    from contextlib import contextmanager

    @contextmanager
    def fake_db_ctx(data, action):
        fields = ", ".join(data.keys())
        values = ", ".join(f"%({k})s" for k in data.keys())
        yield (fake_cursor, fields, values)

    with patch("backend.tool_arena.vote.save_vote_to_database.db", fake_db_ctx):
        save_tool_vote_to_db(payload)

    params = captured["params"]
    assert params["haystack_mode"] == "sandbox"
    assert params["evaluation_query_id"] is None
    assert params["judgement_a"] is None
    assert params["judgement_b"] is None
