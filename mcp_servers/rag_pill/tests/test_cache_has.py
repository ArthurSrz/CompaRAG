"""IndexCache.has(key) — probe API for engine cache_hit emission.

Slice 6.5: engines emit ingest_done(cache_hit=True/False) based on whether
the cache already holds the key before get_or_build is called. The probe
must be fast (no locking) since it runs on every engine call.
"""

import asyncio

import pytest

from mcp_servers.rag_pill.cache import IndexCache


pytestmark = pytest.mark.anyio


async def test_has_returns_false_for_missing_key() -> None:
    cache = IndexCache(max_entries=4)
    assert cache.has(("chroma", "emb", 500, 50, "h1")) is False


async def test_has_returns_true_after_build() -> None:
    cache = IndexCache(max_entries=4)
    key = ("chroma", "emb", 500, 50, "h1")

    async def builder():
        return "built-value"

    await cache.get_or_build(key, builder)
    assert cache.has(key) is True


async def test_has_returns_true_for_different_key_independently() -> None:
    cache = IndexCache(max_entries=4)
    key1 = ("chroma", "emb", 500, 50, "h1")
    key2 = ("chroma", "emb", 500, 50, "h2")

    await cache.get_or_build(key1, lambda: _resolved("a"))
    assert cache.has(key1) is True
    assert cache.has(key2) is False


async def _resolved(value):
    return value
