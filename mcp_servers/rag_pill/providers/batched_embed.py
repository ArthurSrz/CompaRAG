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

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any

import numpy as np

# Same marker the retry wrapper recognizes (retry._EMBEDDING_EMPTY_DATA_MARKER)
# so this module's failures classify identically to the SDK's.
_EMPTY_DATA_MARKER = "No embedding data received"

# Default 4 retries per batch (5 attempts with 1+2+4+8 = 15s backoff).
# Combined with the outer execute_with_embedding_retry (5 attempts,
# 31s backoff) a single transient OpenRouter degradation has a
# multi-minute survival window before reaching the user.
_DEFAULT_BATCH_RETRIES = int(os.environ.get("RAG_PILL_BATCH_RETRIES", "4"))

# Process-global LRU cache of successful per-input embeddings, keyed by
# (model, sha256(input)). Purpose: when the outer execute_with_embedding_retry
# re-runs an engine.execute() after one bad batch, the rebuild reuses the
# vectors we already computed for the good batches. Without this, a 1000-chunk
# document with a single late-failing batch wastes its first 999 batches of
# embedding work on every outer retry — geometric cost amplification that
# surfaces in production as "Engine X failed: No embedding data received"
# even after retries technically completed.
#
# Bounded by RAG_PILL_EMBED_CACHE_SIZE (default 10000 entries — ~60MB for
# 1536-dim float32 vectors). LRU eviction on overflow.
_CACHE_MAX = int(os.environ.get("RAG_PILL_EMBED_CACHE_SIZE", "10000"))
_CACHE: "OrderedDict[tuple[str, str], list[float]]" = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _cache_key(model: str, text: str) -> tuple[str, str]:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return (model, h)


def _cache_get_many(model: str, texts: list[str]) -> list[list[float] | None]:
    """Look up vectors for ``texts``; returns a list aligned to ``texts``
    with None for misses. Touches LRU order on hits."""
    out: list[list[float] | None] = []
    with _CACHE_LOCK:
        for text in texts:
            key = _cache_key(model, text)
            if key in _CACHE:
                _CACHE.move_to_end(key)
                out.append(_CACHE[key])
            else:
                out.append(None)
    return out


def _cache_put_many(model: str, texts: list[str], vectors: list[list[float]]) -> None:
    """Store ``texts`` → ``vectors`` in the cache, evicting LRU entries
    on overflow. Assumes len(texts) == len(vectors)."""
    with _CACHE_LOCK:
        for text, vec in zip(texts, vectors):
            key = _cache_key(model, text)
            _CACHE[key] = vec
            _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def clear_embed_cache() -> None:
    """Test helper — wipe the process-global cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


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
    max_retries_per_batch: int | None = None,
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

    retries = _DEFAULT_BATCH_RETRIES if max_retries_per_batch is None else max_retries_per_batch
    rows: list[list[float]] = []
    for start in range(0, len(inputs), batch_size):
        chunk = inputs[start : start + batch_size]

        # Reuse cached vectors from prior calls (e.g. an outer-retry
        # rebuild that's redoing the same chunk inputs). Only the
        # actually-uncached entries get re-embedded — the rest assemble
        # back into the output in original order.
        cached = _cache_get_many(model, chunk)
        missing_idx = [i for i, v in enumerate(cached) if v is None]
        if not missing_idx:
            rows.extend(v for v in cached if v is not None)
            continue

        missing_inputs = [chunk[i] for i in missing_idx]
        fresh_vectors: list[list[float]] | None = None
        for attempt in range(retries + 1):
            try:
                resp = client.embeddings.create(model=model, input=missing_inputs)
                fresh_vectors = _embeddings_or_raise(resp, expected_count=len(missing_inputs))
                break
            except ValueError as exc:
                if _EMPTY_DATA_MARKER not in str(exc):
                    raise
                if attempt >= retries:
                    raise
                wait = backoff_base * (2 ** attempt)
                log.warning(
                    "batched_embed.empty_data batch_start=%d size=%d missing=%d attempt=%d/%d backoff_s=%s",
                    start, len(chunk), len(missing_inputs),
                    attempt + 1, retries + 1, wait,
                )
                time.sleep(wait)

        # Populate cache for the freshly-fetched vectors so subsequent
        # outer retries (or sibling engines using the same model) skip
        # re-embedding identical inputs.
        assert fresh_vectors is not None  # would have raised above
        _cache_put_many(model, missing_inputs, fresh_vectors)

        # Reassemble in original chunk order — cache hits where present,
        # fresh vectors filled into the missing slots.
        out_chunk: list[list[float] | None] = list(cached)
        for i, vec in zip(missing_idx, fresh_vectors):
            out_chunk[i] = vec
        # All slots are populated now; the cast is safe.
        rows.extend(v for v in out_chunk if v is not None)

    return np.array(rows, dtype=np.float32)
