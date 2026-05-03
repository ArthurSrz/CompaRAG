"""IndexCache — concurrent build serialization and LRU eviction."""

import asyncio

import pytest

from mcp_servers.rag_pill.cache import IndexCache, STATIC_CORPUS_HASH, doc_hash


def test_doc_hash_static_for_empty():
    assert doc_hash("") == STATIC_CORPUS_HASH
    assert doc_hash("   \n") == STATIC_CORPUS_HASH


def test_doc_hash_stable_for_same_content():
    assert doc_hash("abc") == doc_hash("abc")
    assert doc_hash("abc") != doc_hash("abd")


@pytest.mark.anyio
async def test_concurrent_builds_serialized_per_key():
    cache = IndexCache(max_entries=4)
    build_count = 0

    async def builder():
        nonlocal build_count
        build_count += 1
        await asyncio.sleep(0.05)
        return f"index-{build_count}"

    key = ("eng", "embed", 500, 50, "h")
    results = await asyncio.gather(
        cache.get_or_build(key, builder),
        cache.get_or_build(key, builder),
        cache.get_or_build(key, builder),
    )
    assert build_count == 1
    assert results == ["index-1", "index-1", "index-1"]


@pytest.mark.anyio
async def test_lru_eviction():
    cache = IndexCache(max_entries=2)

    async def make_builder(val):
        async def b():
            return val
        return b

    await cache.get_or_build(("e", "x", 1, 1, "a"), await make_builder("A"))
    await cache.get_or_build(("e", "x", 1, 1, "b"), await make_builder("B"))
    # Access "a" to mark it recent
    await cache.get_or_build(("e", "x", 1, 1, "a"), await make_builder("A2"))
    # Insert "c" — should evict "b" (least recently used)
    await cache.get_or_build(("e", "x", 1, 1, "c"), await make_builder("C"))

    # "a" still cached: builder must NOT be called
    builder_called = False

    async def trap():
        nonlocal builder_called
        builder_called = True
        return "X"

    val = await cache.get_or_build(("e", "x", 1, 1, "a"), trap)
    assert val == "A"
    assert builder_called is False


@pytest.fixture
def anyio_backend():
    return "asyncio"
