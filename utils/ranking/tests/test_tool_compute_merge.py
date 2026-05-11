"""Co-tenant aggregation in compute_tool_rankings.

A single RAG engine can be registered under multiple tool_ids (one per
task_type pill). The leaderboard expects one row per engine, so the compute
layer re-IDs votes from tool_id to MCPServerConfig.name before running BT.

Invariants under test:
- Result keys are engine names, not tool_ids
- Intra-engine battles are dropped from BT input AND from preference counts
- n_match per engine sums only inter-engine battles
- Unknown tool_ids fall through unchanged (legacy votes stay visible)
- Ties stay dropped (pre-existing behaviour preserved through the rewrite)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from utils.ranking.tool_compute import (
    _aggregate_tool_preferences,
    _is_retired,
    _resolve_engine,
    _tool_votes_to_battles,
    compute_tool_rankings,
)


def _vote(
    a: str,
    b: str,
    chosen: str,
    *,
    useful_a: bool = False,
    useful_b: bool = False,
    incorrect_a: bool = False,
    incorrect_b: bool = False,
) -> dict:
    """Build a tool_votes row with the 14 pref fields defaulted to False."""
    row: dict = {
        "tool_a_id": a,
        "tool_b_id": b,
        "chosen": chosen,
        "session_hash": "s",
        "task": "t",
        "goal": "g",
        "timestamp": 0,
    }
    for pref in (
        "useful", "complete", "creative", "clear_formatting",
        "incorrect", "superficial", "instructions_not_followed",
    ):
        row[f"vote_{pref}_a"] = False
        row[f"vote_{pref}_b"] = False
    row["vote_useful_a"] = useful_a
    row["vote_useful_b"] = useful_b
    row["vote_incorrect_a"] = incorrect_a
    row["vote_incorrect_b"] = incorrect_b
    return row


# Matches the convention in mcp_servers.json — engine `name` is shared across
# task_type pill variants of the same RAG engine.
NAME_OF = {
    "summary_default__langchain": "LangChain",
    "summary_bullets__langchain": "LangChain",
    "qa_precise__langchain": "LangChain",
    "summary_default__llamaindex": "LlamaIndex",
    "summary_bullets__llamaindex": "LlamaIndex",
    "qa_precise__llamaindex": "LlamaIndex",
    "summary_acme": "Acme",
    "qa_acme": "Acme",
}
KNOWN = {"LangChain", "LlamaIndex", "Acme"}


def test_battles_reid_to_engine_name():
    votes = [
        _vote("summary_default__langchain", "summary_default__llamaindex", "a"),
        _vote("qa_precise__langchain", "qa_precise__llamaindex", "b"),
    ]
    battles = _tool_votes_to_battles(votes, NAME_OF, KNOWN)
    assert battles == [
        ("LangChain", "LlamaIndex", "LangChain"),
        ("LangChain", "LlamaIndex", "LlamaIndex"),
    ]


def test_intra_engine_battles_are_dropped():
    """summary_default__langchain vs summary_bullets__langchain both resolve
    to 'LangChain' — drop, don't emit a 'LangChain vs LangChain' battle."""
    votes = [
        _vote("summary_default__langchain", "summary_bullets__langchain", "a"),
        _vote("summary_default__llamaindex", "qa_precise__llamaindex", "b"),
        # one valid inter-engine battle so we can confirm the rest survives
        _vote("summary_acme", "summary_default__langchain", "a"),
    ]
    battles = _tool_votes_to_battles(votes, NAME_OF, KNOWN)
    assert battles == [("Acme", "LangChain", "Acme")]


def test_retired_engine_votes_are_filtered_from_battles():
    """Withdrawn engines' historical votes must be dropped from leaderboard
    inputs — they would otherwise surface under their raw tool_id or aggregate
    under a no-longer-registered engine name."""
    assert _is_retired("summary_clarifeye")
    assert _is_retired("qa_clarifeye")
    assert _is_retired("clarifeye")
    assert not _is_retired("summary_default__langchain")

    votes = [
        _vote("summary_clarifeye", "summary_default__langchain", "a"),
        _vote("qa_clarifeye", "qa_precise__llamaindex", "b"),
        _vote("summary_default__langchain", "summary_default__llamaindex", "a"),
    ]
    battles = _tool_votes_to_battles(votes, NAME_OF, KNOWN)
    assert battles == [("LangChain", "LlamaIndex", "LangChain")]

    prefs = _aggregate_tool_preferences(votes, NAME_OF, KNOWN)
    assert "Clarifeye" not in prefs
    assert set(prefs.keys()) == {"LangChain", "LlamaIndex"}


def test_ties_stay_dropped():
    votes = [
        _vote("summary_default__langchain", "summary_default__llamaindex", "tie"),
    ]
    assert _tool_votes_to_battles(votes, NAME_OF, KNOWN) == []


def test_truly_unknown_tool_id_falls_through_raw():
    """An id that doesn't match the registry AND has no known-engine substring
    keeps its raw form — visible signal that something is misconfigured."""
    votes = [_vote("retired_tool_xyz", "summary_default__langchain", "a")]
    battles = _tool_votes_to_battles(votes, NAME_OF, KNOWN)
    assert battles == [("retired_tool_xyz", "LangChain", "retired_tool_xyz")]


@pytest.mark.parametrize(
    "legacy_id, expected_engine",
    [
        ("langchain_rag", "LangChain"),
        ("llamaindex_rag", "LlamaIndex"),
        ("acme", "Acme"),                                 # bare engine id
        ("summary_bullets__langchain", "LangChain"),      # retired pill variant
        ("summary_bullets__llamaindex", "LlamaIndex"),
        ("LANGCHAIN_LEGACY", "LangChain"),                # case-insensitive
        ("Acme-experimental", "Acme"),                    # separator-insensitive
    ],
)
def test_legacy_ids_resolve_via_substring(legacy_id, expected_engine):
    """Retired tool_ids absent from the live registry must still fold into
    their engine via substring matching, otherwise they show up as duplicate
    rows on the leaderboard."""
    assert _resolve_engine(legacy_id, {}, KNOWN) == expected_engine


def test_registry_match_takes_precedence_over_substring():
    """When a tool_id IS in the registry, its declared name wins — even if a
    substring match would resolve it to a different engine. (Defensive: if
    someone ever names a registry entry 'fake_langchain_inside' but maps it to
    a separate engine, the JSON wins.)"""
    name_of = {"weird_id": "Custom"}
    known = {"Custom", "LangChain"}
    # weird_id resolves via the registry (Custom), not via substring (LangChain)
    assert _resolve_engine("weird_id", name_of, known) == "Custom"


def test_preferences_aggregate_by_engine():
    votes = [
        _vote(
            "summary_default__langchain", "summary_default__llamaindex", "a",
            useful_a=True, incorrect_b=True,
        ),
        _vote(
            "qa_precise__langchain", "qa_precise__llamaindex", "b",
            useful_b=True, incorrect_a=True,
        ),
    ]
    prefs = _aggregate_tool_preferences(votes, NAME_OF, KNOWN)
    assert set(prefs.keys()) == {"LangChain", "LlamaIndex"}
    # LangChain: 2 votes total, 1 useful, 1 incorrect → ratio = 1/2 = 0.5
    assert prefs["LangChain"].total_prefs == 2
    assert prefs["LangChain"].useful == 1
    assert prefs["LangChain"].incorrect == 1
    assert prefs["LangChain"].positive_prefs_ratio == 0.5
    # LlamaIndex: same shape on the other side
    assert prefs["LlamaIndex"].total_prefs == 2
    assert prefs["LlamaIndex"].useful == 1
    assert prefs["LlamaIndex"].incorrect == 1


def test_preferences_skip_intra_engine_rows():
    """Intra-engine vote rows must not inflate engine pref totals."""
    votes = [
        # Intra-engine — must be excluded entirely
        _vote(
            "summary_default__langchain", "summary_bullets__langchain", "a",
            useful_a=True, useful_b=True,
        ),
        # Real inter-engine vote contributes
        _vote(
            "summary_default__langchain", "summary_default__llamaindex", "a",
            useful_a=True,
        ),
    ]
    prefs = _aggregate_tool_preferences(votes, NAME_OF, KNOWN)
    assert prefs["LangChain"].total_prefs == 1
    assert prefs["LangChain"].useful == 1
    assert prefs["LlamaIndex"].total_prefs == 1
    assert prefs["LlamaIndex"].useful == 0


def _stub_servers():
    """Mimic load_mcp_servers() output with just .id and .name.

    Uses SimpleNamespace because MagicMock(name=...) hijacks the mock's
    display name rather than setting a .name attribute.
    """
    return [SimpleNamespace(id=tid, name=name) for tid, name in NAME_OF.items()]


def test_compute_tool_rankings_collapses_eight_ids_to_three_engines(monkeypatch):
    """End-to-end through compute_tool_rankings: rankings dict has engine names
    as keys, not the per-pill tool_ids."""
    # Build a vote set that produces all three engines as winners at least once
    # (otherwise BT may legitimately exclude an engine that never wins).
    votes = [
        _vote("summary_default__langchain", "summary_default__llamaindex", "a"),
        _vote("summary_default__llamaindex", "qa_precise__langchain", "a"),
        _vote("qa_precise__llamaindex", "qa_precise__langchain", "b"),
        _vote("summary_acme", "summary_default__langchain", "a"),
        _vote("qa_acme", "qa_precise__llamaindex", "a"),
        _vote("summary_default__llamaindex", "summary_acme", "a"),
        # An intra-engine row that must NOT add LangChain↔LangChain to BT
        _vote("summary_default__langchain", "summary_bullets__langchain", "a"),
    ]

    with (
        patch("utils.ranking.tool_compute.fetch_tool_votes", return_value=votes),
        patch(
            "utils.ranking.tool_compute.load_mcp_servers",
            return_value=_stub_servers(),
        ),
    ):
        result = compute_tool_rankings()

    assert result is not None
    assert set(result.rankings.keys()) == {"LangChain", "LlamaIndex", "Acme"}
    assert set(result.preferences.keys()) <= {"LangChain", "LlamaIndex", "Acme"}

    # Each engine's n_match must equal its participation in inter-engine battles
    # only (the intra-engine LangChain vs LangChain row is excluded).
    # row1 LC vs LI       → LC+1, LI+1
    # row2 LI vs LC       → LI+1, LC+1
    # row3 LI vs LC       → LI+1, LC+1
    # row4 AC vs LC       → AC+1, LC+1
    # row5 AC vs LI       → AC+1, LI+1
    # row6 LI vs AC       → LI+1, AC+1
    # row7 intra-LC       → dropped
    # ⇒ LangChain=4, LlamaIndex=5, Acme=3
    assert result.rankings["LangChain"].n_match == 4
    assert result.rankings["LlamaIndex"].n_match == 5
    assert result.rankings["Acme"].n_match == 3
