"""
BUT : exposer le classement actuel des RAGTool — agrégation des Votes calculée
hors-ligne par le cron et stockée dans Redis. Endpoint public, lecture seule.
"""
from __future__ import annotations

import json

from fastapi import APIRouter

from utils.storage.redis import REDIS_TOOL_RANKING_KEY, REDIS_TOOL_RANKING_BY_TASK_KEY, get_redis_client

leaderboard_router = APIRouter()


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
        by_task_type: {                                          # per-pool ELO (null if not yet computed)
          "rag": [{tool_id, elo, ...}, ...],
          "knowledge_capture": [{tool_id, elo, ...}, ...],
          ...
        }
      }

    ``tools`` preserves backward compatibility.
    ``by_task_type`` is the authoritative source for the per-tab leaderboard UI —
    ELO scores are only comparable within the same pool.
    Returns empty lists / null if Redis is unavailable or no data exists yet.
    """
    try:
        client = get_redis_client()
        raw_global = client.get(REDIS_TOOL_RANKING_KEY)
        raw_by_task = client.get(REDIS_TOOL_RANKING_BY_TASK_KEY)
    except Exception:
        return {"data_timestamp": None, "tools": [], "by_task_type": None}

    tools: list[dict] = []
    data_timestamp = None
    if raw_global:
        data = json.loads(raw_global)
        data_timestamp = data.get("timestamp")
        tools = _flatten_ranking(data)

    by_task_type: dict[str, list[dict]] | None = None
    if raw_by_task:
        by_task_raw = json.loads(raw_by_task)
        by_task_type = {
            pool: _flatten_ranking(pool_data)
            for pool, pool_data in by_task_raw.items()
        }

    return {
        "data_timestamp": data_timestamp,
        "tools": tools,
        "by_task_type": by_task_type,
    }
