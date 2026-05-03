"""
Export tool_votes to HuggingFace dataset after each ranking computation.
"""
import logging
import os
import tempfile

import pandas as pd
import psycopg2

from utils.utils import configure_logger

logger = configure_logger(logging.getLogger("ranking.hf_export"))

HF_REPO_ID = "ArthurSrz/comparag-tool-votes"


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
