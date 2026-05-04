"""Pill-setup enrichment for the Hugging Face dataset export.

Each tool_votes row is enriched with eight columns describing the RAG pill
that ran on each side: tool_{a,b}_{pill_id, task_type, engine_id,
engine_name}. Consumers of the public dataset can then interpret a vote
without parsing tool_id strings or fetching the registry separately.

Invariants under test:
- Pill columns appear for both sides for in-registry tool_ids
- Clarifeye-style entries (no pill_id / engine_id in tool_args) get None for
  those two fields but still get task_type and engine_name
- Legacy / retired tool_ids absent from the registry get None across all four
  enrichment fields — they stay in the dataset, just without enrichment
- Original tool_votes columns are preserved unchanged
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from utils.ranking.hf_export import _enrich_with_pill_setup, _setup_for


def _server(
    sid: str,
    name: str,
    *,
    task_type: str | None = None,
    pill_id: str | None = None,
    engine_id: str | None = None,
) -> SimpleNamespace:
    """Stand-in for MCPServerConfig; only the fields _setup_for reads."""
    tool_args: dict[str, str] = {}
    if pill_id is not None:
        tool_args["pill_id"] = pill_id
    if engine_id is not None:
        tool_args["engine_id"] = engine_id
    return SimpleNamespace(
        id=sid, name=name, task_type=task_type, tool_args=tool_args
    )


def test_setup_for_pill_entry():
    s = _server(
        "summary_default__langchain", "LangChain",
        task_type="summary", pill_id="summary_default", engine_id="langchain",
    )
    assert _setup_for(s) == {
        "pill_id": "summary_default",
        "task_type": "summary",
        "engine_id": "langchain",
        "engine_name": "LangChain",
    }


def test_setup_for_clarifeye_style_entry():
    """Clarifeye doesn't expose pill_id / engine_id in tool_args; those two
    fields must come back None while task_type and name still populate."""
    s = _server("summary_clarifeye", "Clarifeye", task_type="summary")
    assert _setup_for(s) == {
        "pill_id": None,
        "task_type": "summary",
        "engine_id": None,
        "engine_name": "Clarifeye",
    }


@pytest.fixture
def fake_registry(monkeypatch):
    servers = [
        _server(
            "summary_default__langchain", "LangChain",
            task_type="summary", pill_id="summary_default", engine_id="langchain",
        ),
        _server(
            "qa_precise__llamaindex", "LlamaIndex",
            task_type="qa", pill_id="qa_precise", engine_id="llamaindex",
        ),
        _server("summary_clarifeye", "Clarifeye", task_type="summary"),
    ]
    monkeypatch.setattr(
        "utils.ranking.hf_export.load_mcp_servers", lambda: servers
    )
    return servers


def _votes_df(rows: list[tuple[str, str]]) -> pd.DataFrame:
    """Build a tool_votes-shaped DataFrame from (tool_a_id, tool_b_id) pairs."""
    return pd.DataFrame(
        [
            {
                "tool_a_id": a,
                "tool_b_id": b,
                "chosen": "a",
                "session_hash": "s",
                "task": "t",
                "goal": "g",
            }
            for a, b in rows
        ]
    )


def test_enrich_in_registry_pair(fake_registry):
    df = _votes_df([("summary_default__langchain", "qa_precise__llamaindex")])
    out = _enrich_with_pill_setup(df)

    row = out.iloc[0]
    assert row["tool_a_pill_id"] == "summary_default"
    assert row["tool_a_task_type"] == "summary"
    assert row["tool_a_engine_id"] == "langchain"
    assert row["tool_a_engine_name"] == "LangChain"
    assert row["tool_b_pill_id"] == "qa_precise"
    assert row["tool_b_task_type"] == "qa"
    assert row["tool_b_engine_id"] == "llamaindex"
    assert row["tool_b_engine_name"] == "LlamaIndex"


def test_enrich_clarifeye_partial_setup(fake_registry):
    df = _votes_df([("summary_clarifeye", "summary_default__langchain")])
    out = _enrich_with_pill_setup(df)

    row = out.iloc[0]
    # Clarifeye side: task_type + engine_name populated, pill_id + engine_id None
    assert row["tool_a_pill_id"] is None
    assert row["tool_a_engine_id"] is None
    assert row["tool_a_task_type"] == "summary"
    assert row["tool_a_engine_name"] == "Clarifeye"


def test_enrich_legacy_tool_id_yields_nulls(fake_registry):
    """Votes for retired tool_ids must keep the row but get None for all four
    enrichment fields on that side."""
    df = _votes_df([("retired_xyz", "summary_default__langchain")])
    out = _enrich_with_pill_setup(df)

    row = out.iloc[0]
    assert row["tool_a_pill_id"] is None
    assert row["tool_a_task_type"] is None
    assert row["tool_a_engine_id"] is None
    assert row["tool_a_engine_name"] is None
    # The other side must still enrich correctly
    assert row["tool_b_engine_name"] == "LangChain"
    # Original columns survive
    assert row["tool_a_id"] == "retired_xyz"
    assert row["chosen"] == "a"


def test_enrich_adds_exactly_eight_columns(fake_registry):
    df = _votes_df([("summary_default__langchain", "qa_precise__llamaindex")])
    before = set(df.columns)
    out = _enrich_with_pill_setup(df)
    new_cols = set(out.columns) - before

    expected = {
        f"tool_{side}_{field}"
        for side in ("a", "b")
        for field in ("pill_id", "task_type", "engine_id", "engine_name")
    }
    assert new_cols == expected


def test_enrich_preserves_original_columns(fake_registry):
    df = _votes_df([("summary_default__langchain", "qa_precise__llamaindex")])
    original = df.copy()
    out = _enrich_with_pill_setup(df)
    for col in original.columns:
        assert (out[col] == original[col]).all()
