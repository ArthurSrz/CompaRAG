"""
BUT : exposer le classement actuel des RAGTool — agrégation des Votes calculée
hors-ligne par le cron et stockée dans Redis. Endpoint public, lecture seule.
"""
from __future__ import annotations

import json

from fastapi import APIRouter

from utils.storage.redis import REDIS_TOOL_RANKING_KEY, get_redis_client

leaderboard_router = APIRouter()


@leaderboard_router.get("/leaderboard")
async def get_tool_leaderboard():
    """
    Return current tool rankings from Redis.

    Response shape: {data_timestamp: float|null, tools: [{tool_id, elo, ..., prefs: {...}|null}, ...]}
    Each tool entry merges the ranking row with its preferences block (or null
    if no prefs aggregated yet — mirrors LLM /models endpoint shape).
    Returns empty tools list if Redis is unavailable or no data exists yet.
    """
    try:
        client = get_redis_client()
        raw = client.get(REDIS_TOOL_RANKING_KEY)
    except Exception:
        return {"data_timestamp": None, "tools": []}
    if not raw:
        return {"data_timestamp": None, "tools": []}
    data = json.loads(raw)
    rankings = data.get("rankings", {})
    preferences = data.get("preferences", {})
    tools = [
        {**entry, "prefs": preferences.get(tool_id)}
        for tool_id, entry in rankings.items()
    ]
    return {
        "data_timestamp": data.get("timestamp"),
        "tools": tools,
    }
