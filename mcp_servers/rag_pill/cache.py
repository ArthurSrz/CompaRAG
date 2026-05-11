"""Index cache — LRU keyed on (engine_id, embedder, chunk_size, chunk_overlap, doc_hash).

One asyncio.Lock per cache key prevents two concurrent requests from double-building
the same index. FAISS reads are thread-safe; only the build needs serialization.
"""

import asyncio
import hashlib
from collections import OrderedDict
from typing import Awaitable, Callable

CacheKey = tuple[str, str, int, int, str]
STATIC_CORPUS_HASH = "STATIC_CORPUS"


def doc_hash(content: str) -> str:
    if not content.strip():
        return STATIC_CORPUS_HASH
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class IndexCache:
    def __init__(self, max_entries: int = 32) -> None:
        self._entries: OrderedDict[CacheKey, object] = OrderedDict()
        self._locks: dict[CacheKey, asyncio.Lock] = {}
        self._max = max_entries

    def _lock(self, key: CacheKey) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def has(self, key: CacheKey) -> bool:
        """True iff a built index is currently cached for this key.

        Race-safe at the API boundary: a True here means the next
        get_or_build will skip the builder (engine should emit cache_hit=True).
        A False might race a concurrent build — emitting cache_hit=False is
        the right call in that case (caller waited for the build, so the
        ingest cost was paid from this caller's perspective).
        """
        return key in self._entries

    async def get_or_build(
        self,
        key: CacheKey,
        builder: Callable[[], Awaitable[object]],
    ) -> object:
        async with self._lock(key):
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key]
            index = await builder()
            self._entries[key] = index
            if len(self._entries) > self._max:
                evicted_key, _ = self._entries.popitem(last=False)
                self._locks.pop(evicted_key, None)
            return index
