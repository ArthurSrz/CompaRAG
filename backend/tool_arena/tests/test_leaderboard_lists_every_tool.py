"""The leaderboard lists every registered tool, scored or not.

The ranking is computed from votes, so a tool that never completed a duel —
a newly added engine, or one broken since the day it shipped — was absent
from the page entirely. Absent reads as "does not exist", which is a
different claim from "has no score yet", and the second is the true one.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tool_arena.leaderboard.show_leaderboard_endpoint import leaderboard_router


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(leaderboard_router, prefix="/tool-arena")
    return TestClient(app)


def _redis_with(global_payload: dict | None, by_task: dict | None):
    fake = MagicMock()
    fake.get.side_effect = lambda key: (
        json.dumps(global_payload)
        if "BY_TASK" not in key.upper() and global_payload is not None
        else json.dumps(by_task) if by_task is not None else None
    )
    return fake


def _entry(tool: str, elo: int) -> dict:
    return {
        "tool_id": tool,
        "elo": elo,
        "score_p2_5": elo - 20,
        "score_p97_5": elo + 20,
        "rank": 1,
        "n_match": 12,
        "win_rate": 0.5,
        "provisional": False,
    }


def _by_name(payload: list[dict]) -> dict[str, dict]:
    return {entry["tool_id"]: entry for entry in payload}


def test_a_tool_with_no_vote_is_listed_without_a_score(client):
    ranked = {"rankings": {"LangChain": _entry("LangChain", 1100)}, "preferences": {}}
    with patch(
        "backend.tool_arena.leaderboard.show_leaderboard_endpoint.get_redis_client",
        return_value=_redis_with(ranked, {"rag": ranked}),
    ):
        body = client.get("/tool-arena/leaderboard").json()

    rag = _by_name(body["by_task_type"]["rag"])
    assert rag["LangChain"]["elo"] == 1100
    # BM25 shipped 2026-10-10 and lost every duel to a connection error, so it
    # has no vote at all — and was invisible here until now.
    assert "BM25" in rag
    assert rag["BM25"]["elo"] is None
    assert rag["BM25"]["n_match"] == 0


def test_unrated_tools_come_after_the_ranked_ones(client):
    ranked = {"rankings": {"LangChain": _entry("LangChain", 1100)}, "preferences": {}}
    with patch(
        "backend.tool_arena.leaderboard.show_leaderboard_endpoint.get_redis_client",
        return_value=_redis_with(ranked, {"rag": ranked}),
    ):
        rag = client.get("/tool-arena/leaderboard").json()["by_task_type"]["rag"]
    assert rag[0]["tool_id"] == "LangChain"
    assert all(entry["elo"] is None for entry in rag[1:])


def test_an_unrated_tool_is_not_flagged_provisional_against_zero_duels(client):
    """`provisional` is true for a thin sample; with no sample at all the
    reader needs "no duel yet", not "provisional score"."""
    with patch(
        "backend.tool_arena.leaderboard.show_leaderboard_endpoint.get_redis_client",
        return_value=_redis_with(None, None),
    ):
        body = client.get("/tool-arena/leaderboard").json()
    for entry in body["tools"]:
        assert entry["n_match"] == 0
        assert entry["elo"] is None


def test_both_pools_are_listed_even_before_any_vote(client):
    with patch(
        "backend.tool_arena.leaderboard.show_leaderboard_endpoint.get_redis_client",
        return_value=_redis_with(None, None),
    ):
        body = client.get("/tool-arena/leaderboard").json()
    assert set(body["by_task_type"]) == {"rag", "knowledge_capture"}
    assert body["by_task_type"]["knowledge_capture"], "interview tools must be listed too"


def test_redis_down_still_names_every_tool(client):
    """Without scores the page is thin, but "which tools exist" is read from
    the registry and still answerable."""
    failing = MagicMock()
    failing.get.side_effect = RuntimeError("redis down")
    with patch(
        "backend.tool_arena.leaderboard.show_leaderboard_endpoint.get_redis_client",
        return_value=failing,
    ):
        body = client.get("/tool-arena/leaderboard").json()
    names = {entry["tool_id"] for entry in body["tools"]}
    assert {"LangChain", "BM25", "Hybride", "PageIndex"} <= names
    assert body["data_timestamp"] is None
