"""Tests for the 1-5 goal-attainment rating on tool votes.

The pill-flag UI was replaced with a single star rating per side. Backend
contract:
- ``ToolPreferencesPayload.vote_goal_rating_{a,b}`` accepts integers 1..5 or
  None; anything else raises ValidationError.
- ``ToolVoteRecord`` carries the rating through to the INSERT data dict so
  the DB column is populated when the user rates.
- Legacy clients that omit the rating still vote successfully (None values).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.tool_arena.vote.save_vote_to_database import ToolVoteRecord
from backend.tool_arena.router import ToolPreferencesPayload


# --- ToolPreferencesPayload validation ----------------------------------------


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5, None])
def test_payload_accepts_valid_rating(value):
    p = ToolPreferencesPayload(
        vote_goal_rating_a=value, vote_goal_rating_b=value
    )
    assert p.vote_goal_rating_a == value
    assert p.vote_goal_rating_b == value


@pytest.mark.parametrize("value", [0, 6, -1, 100])
def test_payload_rejects_out_of_range(value):
    with pytest.raises(ValidationError):
        ToolPreferencesPayload(vote_goal_rating_a=value)
    with pytest.raises(ValidationError):
        ToolPreferencesPayload(vote_goal_rating_b=value)


def test_payload_defaults_to_none():
    """A client that doesn't supply a rating gets None on both sides."""
    p = ToolPreferencesPayload()
    assert p.vote_goal_rating_a is None
    assert p.vote_goal_rating_b is None


def test_payload_keeps_legacy_pill_fields_back_compat():
    """The 14 vote_<pref>_<side> booleans still parse so historical clients
    do not break — they just default to False going forward."""
    p = ToolPreferencesPayload(vote_useful_a=True, vote_incorrect_b=True)
    assert p.vote_useful_a is True
    assert p.vote_incorrect_b is True
    # And the rating is independent of the pill flags
    assert p.vote_goal_rating_a is None


def test_payload_per_side_independence():
    """Rating one side without rating the other is allowed."""
    p = ToolPreferencesPayload(vote_goal_rating_a=4)
    assert p.vote_goal_rating_a == 4
    assert p.vote_goal_rating_b is None


# --- ToolVoteRecord round-trip ------------------------------------------------


def _record(**overrides) -> ToolVoteRecord:
    base = dict(
        session_hash="s",
        tool_a_id="t_a",
        tool_b_id="t_b",
        chosen="a",
        llm_id="m",
        task="t",
        goal="g",
        timestamp="2026-05-04T18:15:00",
    )
    base.update(overrides)
    return ToolVoteRecord(**base)


def test_record_includes_rating_columns_in_dump():
    """model_dump must surface the new rating fields so save_tool_vote_to_db
    can splat them straight into the INSERT."""
    r = _record(vote_goal_rating_a=5, vote_goal_rating_b=3)
    dump = r.model_dump(mode="json")
    assert dump["vote_goal_rating_a"] == 5
    assert dump["vote_goal_rating_b"] == 3


def test_record_rating_none_when_unset():
    r = _record()
    dump = r.model_dump(mode="json")
    assert dump["vote_goal_rating_a"] is None
    assert dump["vote_goal_rating_b"] is None


def test_record_dump_preserves_legacy_pref_columns():
    """The 14 vote_<pref>_<side> columns must still appear in the dump so
    historical pref data continues to write correctly."""
    r = _record(vote_useful_a=True)
    dump = r.model_dump(mode="json")
    expected = {
        f"vote_{pref}_{side}"
        for side in ("a", "b")
        for pref in (
            "useful", "complete", "creative", "clear_formatting",
            "incorrect", "superficial", "instructions_not_followed",
        )
    }
    assert expected <= set(dump.keys())
    # And the new columns are also present
    assert {"vote_goal_rating_a", "vote_goal_rating_b"} <= set(dump.keys())
