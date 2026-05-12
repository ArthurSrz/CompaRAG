"""Fan a long input list across the OpenAI embeddings API in fixed-size
batches with per-batch retry.

Why this exists
---------------
OpenRouter intermittently returns 200 OK with empty (or None-valued)
embedding data on large batches. The legacy retry guard restarts the
*entire* engine.execute() — so a single bad batch wastes the work already
done on the good batches and gets the same all-at-once payload on retry,
re-firing the same upstream flake. Moving the retry boundary down to the
batch level fixes both problems: bad batches cost one batch's work, and
each retry pings a much smaller payload that the upstream is more likely
to handle.

Used by every engine that builds its own embedder (currently txtai;
library-wrapped engines like langchain/llamaindex/haystack expose their
own batch_size knob and rely on the same per-batch retry there).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

# Same marker the retry wrapper recognizes (retry._EMBEDDING_EMPTY_DATA_MARKER)
# so this module's failures classify identically to the SDK's.
_EMPTY_DATA_MARKER = "No embedding data received"

log = logging.getLogger("rag_pill")


def _embeddings_or_raise(resp: Any, expected_count: int) -> list[list[float]]:
    """Extract the embedding vectors from an OpenAI-shaped response.

    Raises ValueError(_EMPTY_DATA_MARKER) when the response is None,
    lacks a data array, returns fewer items than requested, or contains
    any None-valued embedding. Both shapes are real production failures.
    """
    if resp is None:
        raise ValueError(_EMPTY_DATA_MARKER)
    data = getattr(resp, "data", None)
    if not data or len(data) < expected_count:
        raise ValueError(_EMPTY_DATA_MARKER)
    vectors: list[list[float]] = []
    for item in data:
        vec = getattr(item, "embedding", None)
        if vec is None:
            raise ValueError(_EMPTY_DATA_MARKER)
        vectors.append(vec)
    return vectors


def batched_embed(
    client: Any,
    *,
    model: str,
    inputs: list[str],
    batch_size: int,
    max_retries_per_batch: int = 2,
    backoff_base: float = 1.0,
) -> np.ndarray:
    """Embed ``inputs`` in groups of ``batch_size``; retry each failing batch.

    Returns a (len(inputs), dim) float32 numpy array. Raises
    ``ValueError(_EMPTY_DATA_MARKER)`` after the final retry attempt on
    the first batch that exhausts its budget — the same marker the outer
    retry wrapper already recognizes.
    """
    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive, got {batch_size}")
    if not inputs:
        return np.zeros((0, 0), dtype=np.float32)

    rows: list[list[float]] = []
    for start in range(0, len(inputs), batch_size):
        chunk = inputs[start : start + batch_size]
        for attempt in range(max_retries_per_batch + 1):
            try:
                resp = client.embeddings.create(model=model, input=chunk)
                vectors = _embeddings_or_raise(resp, expected_count=len(chunk))
                rows.extend(vectors)
                break
            except ValueError as exc:
                if _EMPTY_DATA_MARKER not in str(exc):
                    raise
                if attempt >= max_retries_per_batch:
                    raise
                wait = backoff_base * (2 ** attempt)
                log.warning(
                    "batched_embed.empty_data batch_start=%d size=%d attempt=%d/%d backoff_s=%s",
                    start, len(chunk), attempt + 1, max_retries_per_batch + 1, wait,
                )
                time.sleep(wait)

    return np.array(rows, dtype=np.float32)
