"""
Script computing ranking/preferences and stores results in redis or as json file.
Ran at interval by a cronjob.
"""

# --- Module-load sentinel: proves the script was actually invoked. ----------
# Written before ANY other import that could fail. If this row never appears in
# cron_sentinel, then `uv run python -m utils.ranking.run` is not being executed
# at all — the issue is upstream (start command, build, etc.), not the code.
import os as _sentinel_os
import sys as _sentinel_sys
import traceback as _sentinel_tb
import datetime as _sentinel_dt

try:
    import psycopg2 as _sentinel_pg
    _db = _sentinel_os.environ.get("COMPARIA_DB_URI")
    if _db:
        _conn = _sentinel_pg.connect(_db)
        _conn.autocommit = True
        _cur = _conn.cursor()
        _cur.execute("CREATE TABLE IF NOT EXISTS cron_sentinel (id SERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT NOW(), msg TEXT)")
        _cur.execute(
            "INSERT INTO cron_sentinel (msg) VALUES (%s)",
            (f"module-load@{_sentinel_dt.datetime.utcnow().isoformat()}Z argv={_sentinel_sys.argv}",),
        )
        _conn.close()
        print("[CRON_SENTINEL] module-load wrote to cron_sentinel", flush=True)
except Exception:
    print(f"[CRON_SENTINEL] module-load failed: {_sentinel_tb.format_exc()[-500:]}", flush=True)
# ---------------------------------------------------------------------------

import json
import logging
from pathlib import Path
from typing import Literal

import cyclopts
from fastapi.encoders import jsonable_encoder

import os
import time
import traceback
from utils.storage.redis import REDIS_RANKING_KEY, REDIS_TOOL_RANKING_KEY, get_redis_client

CRON_DIAG_KEY = "ranking_cron:last_run_diag"
_diag_steps: list[dict] = []


def _diag(step: str, **kwargs) -> None:
    """Append a diagnostic step to in-memory log; persisted to Redis at end of run.

    Visible from outside the cron container by reading CRON_DIAG_KEY via the
    Redis public proxy. Used to debug silent failures since Railway logs are
    not reliably surfaceable for cron services.
    """
    _diag_steps.append({"t": time.time(), "step": step, **kwargs})
    print(f"[CRON_DIAG] {step}: {kwargs}", flush=True)


def _flush_diag() -> None:
    payload = json.dumps({
        "started_at": _diag_steps[0]["t"] if _diag_steps else None,
        "ended_at": time.time(),
        "hf_token_present": bool(os.environ.get("HF_TOKEN")),
        "redis_host": os.environ.get("COMPARIA_REDIS_HOST", ""),
        "db_uri_host": (os.environ.get("COMPARIA_DB_URI", "").split("@")[-1].split("/")[0]
                        if "@" in os.environ.get("COMPARIA_DB_URI", "") else None),
        "steps": _diag_steps,
    })
    print(f"[CRON_DIAG] payload size={len(payload)}", flush=True)

    # Try Redis (preferred — fast, structured). Catch all so a Redis outage
    # doesn't block the Postgres fallback below.
    try:
        client = get_redis_client()
        client.setex(CRON_DIAG_KEY, time=3600 * 24, value=payload)
        print("[CRON_DIAG] redis_write: ok", flush=True)
    except Exception:
        print(f"[CRON_DIAG] redis_write: FAILED {traceback.format_exc()[-1000:]}", flush=True)

    # Also write to Postgres (independent infrastructure — survives Redis outage).
    try:
        import psycopg2
        conn = psycopg2.connect(os.environ["COMPARIA_DB_URI"])
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cron_diagnostics (
                id SERIAL PRIMARY KEY,
                ts TIMESTAMPTZ DEFAULT NOW(),
                payload JSONB
            )
        """)
        cur.execute("INSERT INTO cron_diagnostics (payload) VALUES (%s::jsonb)", (payload,))
        conn.close()
        print("[CRON_DIAG] postgres_write: ok", flush=True)
    except Exception:
        print(f"[CRON_DIAG] postgres_write: FAILED {traceback.format_exc()[-1000:]}", flush=True)
from utils.utils import (
    LLMS_GENERATED_DATA_FILE,
    configure_logger,
    read_json,
    write_json,
)

from .compute import DataGroup, RankingResult, compute_all_rankings
from .hf_export import export_tool_votes_to_hf
from .monitor import monitor
from .tool_compute import compute_tool_rankings

logger = configure_logger(logging.getLogger("ranking.run"))

LLMS_RANKING_DATA_FILE = Path(__file__).parent / "generated-ranking-all.json"


def store_to_redis(group: DataGroup, data: RankingResult) -> None:
    """
    Stores per group (portals + all) `RankingResult` in redis cache for comparia instances.

    Note:
        Expires after 24 hours but should be recomputed at interval with a cronjob.
    """
    data_info = f"ranking and prefs data for group: {group}"

    try:
        client = get_redis_client()
        client.setex(
            REDIS_RANKING_KEY.format(country_portal=group),
            time=3600 * 24,
            value=json.dumps(data),
        )
        logger.info(f"[SESSION] Stored {data_info}")
    except Exception as e:
        logger.error(f"[SESSION] Error storing {data_info}: {e}")
        raise


def main(mode: Literal["all", "redis", "json"] = "redis") -> None:
    """
    Compute per group (portals + "all") `RankingResult` in redis/as file depending on mode.

    Tool ranking + HF export run unconditionally; they are isolated from the LLM
    ranking path (see tool_compute.py header) and must not be gated by LLM data.
    """
    _diag("main:start", mode=mode)
    try:
        _diag("tool_rankings:start")
        compute_and_store_tool_rankings()
        _diag("tool_rankings:done")
    except Exception as e:
        _diag("tool_rankings:exception", error=repr(e), tb=traceback.format_exc())

    try:
        _diag("hf_export:start")
        export_tool_votes_to_hf()
        _diag("hf_export:done")
    except Exception as e:
        _diag("hf_export:exception", error=repr(e), tb=traceback.format_exc()[-2000:])

    try:
        _diag("compute_all_rankings:start")
        data = compute_all_rankings()
        _diag("compute_all_rankings:done", n_groups=len(data) if data else 0)
    except Exception as e:
        _diag("compute_all_rankings:exception", error=repr(e), tb=traceback.format_exc()[-2000:])
        data = {}

    if not data:
        logger.info("[Ranking] No LLM ranking data to store, skipping LLM-side outputs.")
        _flush_diag()
        return

    if mode in ("all", "json"):
        # FIXME reflect previous data structure and override utils/models/generated-models-extra-data.json?
        write_json(LLMS_RANKING_DATA_FILE, jsonable_encoder(data["all"]))

    if mode in ("all", "redis"):
        for k in data.keys():
            store_to_redis(k, jsonable_encoder(data[k]))

    llms = read_json(LLMS_GENERATED_DATA_FILE)["models"]
    monitor(llms, data["all"])
    _flush_diag()


def compute_and_store_tool_rankings() -> None:
    """Compute tool rankings and store to Redis under REDIS_TOOL_RANKING_KEY."""
    try:
        result = compute_tool_rankings()
        if result is None:
            return
        client = get_redis_client()
        client.setex(
            REDIS_TOOL_RANKING_KEY,
            time=3600 * 24,
            value=json.dumps(jsonable_encoder(result)),
        )
        logger.info("[ToolRanking] Stored tool rankings to Redis")
    except Exception as e:
        logger.error(f"[ToolRanking] Error storing tool rankings: {e}")


if __name__ == "__main__":
    cyclopts.run(main)
