"""
Export tool_votes to HuggingFace dataset after each ranking computation.
"""
import logging
import os
import tempfile

import pandas as pd
import psycopg2

from backend.tool_arena.config import MCPServerConfig, load_mcp_servers
from utils.utils import configure_logger

logger = configure_logger(logging.getLogger("ranking.hf_export"))

HF_REPO_ID = "ArthurSrz/comparag-tool-votes"

# Per-side enrichment columns derived from mcp_servers.json. Consumers of the
# HF dataset can interpret a vote without parsing tool_id strings or fetching
# the registry separately. Legacy tool_ids that no longer appear in the
# registry get NULL across all four fields.
_SIDE_COLUMNS = ("pill_id", "task_type", "engine_id", "engine_name")


def _setup_for(server: MCPServerConfig) -> dict[str, str | None]:
    """Extract the four pill-setup fields for a registry entry.

    Clarifeye-style entries don't carry ``pill_id`` / ``engine_id`` in
    ``tool_args`` (they pass ``project_id`` / ``agent_settings_id`` instead),
    so those keys come back as ``None`` — same shape as a legacy fallthrough.
    """
    return {
        "pill_id": server.tool_args.get("pill_id"),
        "task_type": server.task_type,
        "engine_id": server.tool_args.get("engine_id"),
        "engine_name": server.name,
    }


def _build_setup_map() -> dict[str, dict[str, str | None]]:
    """tool_id → {pill_id, task_type, engine_id, engine_name}. Loaded once."""
    return {s.id: _setup_for(s) for s in load_mcp_servers()}


def _enrich_with_pill_setup(df: pd.DataFrame) -> pd.DataFrame:
    """Add tool_{a,b}_{pill_id, task_type, engine_id, engine_name} columns.

    Looks each tool_id up in the current registry. Unknown ids (legacy votes
    for retired entries) get None across all four side-columns; they are still
    present in the dataset, just without enrichment.
    """
    setup_map = _build_setup_map()
    empty = {col: None for col in _SIDE_COLUMNS}

    for side in ("a", "b"):
        side_setup = df[f"tool_{side}_id"].map(
            lambda tid, _m=setup_map, _e=empty: _m.get(tid, _e)
        )
        for col in _SIDE_COLUMNS:
            df[f"tool_{side}_{col}"] = side_setup.map(lambda d, _c=col: d[_c])
    return df


def export_tool_votes_to_hf() -> None:
    db_uri = os.environ.get("COMPARIA_DB_URI")
    hf_token = os.environ.get("HF_TOKEN")

    if not db_uri:
        logger.warning("[HF Export] COMPARIA_DB_URI not set, skipping.")
        return
    if not hf_token:
        logger.warning("[HF Export] HF_TOKEN not set, skipping.")
        return

    logger.info("[HF Export] Starting export_tool_votes_to_hf")
    try:
        from huggingface_hub import HfApi

        logger.info("[HF Export] Connecting to Postgres")
        conn = psycopg2.connect(db_uri)
        df = pd.read_sql("SELECT * FROM tool_votes ORDER BY timestamp DESC", conn)
        conn.close()
        logger.info(f"[HF Export] Fetched {len(df)} rows, columns={list(df.columns)}")

        if df.empty:
            logger.info("[HF Export] No tool_votes rows, skipping.")
            return

        df = _enrich_with_pill_setup(df)
        logger.info(
            f"[HF Export] Enriched with pill setup, columns={list(df.columns)}"
        )

        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            df.to_parquet(f.name, index=False)
            tmp_path = f.name
        logger.info(f"[HF Export] Wrote parquet to {tmp_path}")

        api = HfApi(token=hf_token)
        logger.info(f"[HF Export] Uploading to {HF_REPO_ID}")
        api.upload_file(
            path_or_fileobj=tmp_path,
            path_in_repo="tool_votes.parquet",
            repo_id=HF_REPO_ID,
            repo_type="dataset",
            commit_message=f"Auto-update: {len(df)} votes",
        )
        logger.info(f"[HF Export] Pushed {len(df)} rows to {HF_REPO_ID}")

    except Exception:
        logger.exception("[HF Export] Failed")
        raise
