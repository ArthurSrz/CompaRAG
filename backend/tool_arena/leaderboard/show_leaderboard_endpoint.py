"""
BUT : exposer le classement actuel des RAGTool — agrégation des Votes calculée
hors-ligne par le cron et stockée dans Redis. Endpoint public, lecture seule.
"""
from __future__ import annotations

import json

from fastapi import APIRouter

from backend.tool_arena.config import load_mcp_servers
from utils.storage.redis import REDIS_TOOL_RANKING_KEY, REDIS_TOOL_RANKING_BY_TASK_KEY, get_redis_client

leaderboard_router = APIRouter()

# Pool key for everything that is not an interview — same rule as
# utils/ranking/tool_compute.py::_task_type_map, where summary, qa and
# extraction share one leaderboard.
_DEFAULT_POOL = "rag"


def _roster() -> dict[str, list[str]]:
    """Every tool the arena can draw, by pool, as display names.

    The rankings only know tools that have been voted on, so a tool that has
    never completed a duel — a newly added engine, or one broken since the
    day it shipped — was simply absent from the leaderboard, which read as if
    it did not exist. It does exist; it has no score yet, and that is a
    different statement.
    """
    pools: dict[str, list[str]] = {}
    for server in load_mcp_servers():
        pool = server.task_type if server.task_type == "knowledge_capture" else _DEFAULT_POOL
        names = pools.setdefault(pool, [])
        # One name covers several (pill, engine) entries — the rankings
        # aggregate them under that name too.
        if server.name not in names:
            names.append(server.name)
    return pools


def _unrated(name: str) -> dict:
    """A tool with no duel behind it. Null scores, not zeroed ones: a zero
    would sort and plot as a real, very bad Elo."""
    return {
        "tool_id": name,
        "elo": None,
        "score_p2_5": None,
        "score_p97_5": None,
        "rank": None,
        "n_match": 0,
        "win_rate": 0.0,
        "provisional": True,
        "prefs": None,
    }


def _with_every_tool(ranked: list[dict], names: list[str]) -> list[dict]:
    """Ranked tools first, then the ones still waiting for their first duel."""
    seen = {entry.get("tool_id") for entry in ranked}
    return ranked + [_unrated(name) for name in names if name not in seen]


def _flatten_ranking(data: dict) -> list[dict]:
    """Merge rankings + preferences into a flat list of tool dicts."""
    rankings = data.get("rankings", {})
    preferences = data.get("preferences", {})
    return [
        {**entry, "prefs": preferences.get(tool_id)}
        for tool_id, entry in rankings.items()
    ]


@leaderboard_router.get("/leaderboard")
async def get_tool_leaderboard():
    """
    Return current tool rankings from Redis.

    Response shape:
      {
        data_timestamp: float|null,
        tools: [{tool_id, elo, ..., prefs: {...}|null}, ...],   # global (all pools merged)
        by_task_type: {                                          # per-pool ELO
          "rag": [{tool_id, elo, ...}, ...],
          "knowledge_capture": [{tool_id, elo, ...}, ...],
          ...
        }
      }

    Every registered tool is listed, scored or not: one that has never
    completed a duel comes back with ``elo: null`` and ``n_match: 0``, after
    the ranked ones. Absent and unrated are different claims, and only the
    second is true of a tool the arena can still draw.

    ``tools`` preserves backward compatibility.
    ``by_task_type`` is the authoritative source for the per-tab leaderboard UI —
    ELO scores are only comparable within the same pool.
    """
    try:
        client = get_redis_client()
        raw_global = client.get(REDIS_TOOL_RANKING_KEY)
        raw_by_task = client.get(REDIS_TOOL_RANKING_BY_TASK_KEY)
    except Exception:
        # Redis down: no scores, but the roster is read from the registry and
        # still answers "which tools exist", which is most of what the page
        # is for.
        roster = _roster()
        return {
            "data_timestamp": None,
            "tools": [_unrated(n) for names in roster.values() for n in names],
            "by_task_type": {
                pool: [_unrated(n) for n in names] for pool, names in roster.items()
            },
        }

    tools: list[dict] = []
    data_timestamp = None
    if raw_global:
        data = json.loads(raw_global)
        data_timestamp = data.get("timestamp")
        tools = _flatten_ranking(data)

    by_task_raw = json.loads(raw_by_task) if raw_by_task else {}
    roster = _roster()
    by_task_type = {
        pool: _with_every_tool(
            _flatten_ranking(by_task_raw.get(pool) or {}), names
        )
        for pool, names in roster.items()
    }
    tools = _with_every_tool(tools, [n for names in roster.values() for n in names])

    return {
        "data_timestamp": data_timestamp,
        "tools": tools,
        "by_task_type": by_task_type,
    }
