# Phase 14: Engine Hardening (chromadb + None-embedding defenses) — Context

**Gathered:** 2026-05-13
**Status:** Shipped (commits e579b024, 5759bd8c, d9f5bf87 on develop)
**Milestone:** v1.2 — Document Context Selection
**Source:** Production bug — user-visible screenshot 2026-05-12 with both tools failing on `chroma_baseline`; follow-up report 2026-05-13 of `'NoneType' object is not subscriptable` on `haystack`.

<domain>
## Phase Boundary

Stop the tool-arena from leaking infrastructure failures into user-visible "Engine X failed: …" cards. Three root causes hit the UI in the last 48h:

1. **chromadb 1.x EphemeralClient race** — two arena sides each constructing their own `chromadb.EphemeralClient()` from different threadpool workers raced chromadb's process-global `SharedSystemClient` cache. Surfaced as either `'RustBindingsAPI' object has no attribute 'bindings'` (bindings not yet initialized) or `KeyError: 'ephemeral'` (cache evicted between lookup and use).

2. **chromadb collection leak after IndexCache eviction** — the singleton client introduced by fix #1 owned the canonical refs to every cached collection. IndexCache evicting its entry only dropped the Python wrapper; the collection persisted in chromadb's internal map. Over a long-running server, embeddings for evicted uploads accumulated unboundedly.

3. **`'NoneType' object is not subscriptable` leaks across engines** — OpenRouter intermittently returns 200 OK with `None`-valued embeddings. The retry matcher in `retry.py` only caught `isinstance(exc, TypeError)` / `isinstance(exc, ValueError)` — frameworks (haystack components, langchain runnables, llamaindex callbacks) sometimes re-raise the TypeError wrapped in their own class, escaping the retry. Additionally, three of the five engines (chroma, langchain, llamaindex) had no boundary validator, so the None could propagate deep into framework code before being subscripted.

**In scope (delivered):**
- Module-level chromadb singleton + asyncio.Lock to serialize first-touch.
- `_CollectionHandle` wrapper with `weakref.finalize(handle, client.delete_collection, name)` so IndexCache eviction triggers a real collection cleanup.
- `_is_empty_embedding_data_error` widened to message-substring matching across any exception class with `__cause__`/`__context__` chain walking (defensive against pathological loops via visited-id tracking).
- `validate_vector_list` helper in `providers/embedding_validator.py` — preserves inner vector identity (chromadb's `OpenAIEmbeddingFunction` returns `list[np.float32]` and rejects anything cast through Python `float`).
- Boundary validators wired into the three previously unprotected engines:
  - `langchain_engine.py` — pre-embed via `embeddings.embed_documents`, validate, hand `(text, vector)` pairs to `FAISS.from_embeddings`.
  - `llamaindex_engine.py` — probe `Settings.embed_model.get_text_embedding_batch` on a single chunk, validate, then call `VectorStoreIndex.from_documents`.
  - `chroma_baseline_engine.py` — subclass `OpenAIEmbeddingFunction` to validate inside `__call__` so the None never reaches `collection.upsert`.
- Default `RAG_PILL_EMBEDDING_RETRIES` bumped from `2` → `4` (5 attempts, 1+2+4+8+16 = 31s window).
- Modernization sweep: `asyncio.get_event_loop()` → `asyncio.get_running_loop()` in all 5 engines (3.14 readiness).
- Stale test removal: `test_both_mcp_calls_receive_identical_task_prompt` patched a `dispatcher.litellm` symbol that no longer exists; the invariant is already covered by `test_dispatcher.py::test_dispatch_passes_identical_task_goal_to_both`.

**Out of scope (deliberately):**
- Fixing OpenRouter's upstream degradation — not ours to fix.
- Per-engine retry budget tuning — single env knob is enough.
- Replacing chromadb's `EphemeralClient` with `PersistentClient` — the singleton path is simpler and matches the in-memory perf contract.
- Dispatcher pool=2 "footgun" from memory — re-examined and found to be a non-issue (when the pool is exactly 2, you must pick both; weights mathematically can't change selection).

</domain>

<verification>
## How we know it's done

- `uv run pytest backend/ mcp_servers/rag_pill/tests/ -q -k "not smoke"` → 359 pass / 0 fail (baseline was 243 + 108 before stale-test removal).
- Browser-harness 10-round stress test post commit `e579b024`: 10/10 clean, zero engine errors. (`/tmp/round-*-error.png` empty, summary `Total: 10, Errors: 0`.)
- The 3 pre-existing rag_pill smoke-test failures are corpus-fixture gaps (`mcp_servers/rag_pill/corpus/` has no `.md` docs) — unrelated to this phase.
- Production verification of NoneType-subscript fix awaits the Railway build of commit `d9f5bf87` (triggered via git push per the updated rag-pill workflow).
</verification>

<artifacts>
## Commits on `develop`

- `e579b024` — chromadb singleton + lock (race fix)
- `5759bd8c` — `_CollectionHandle` + `weakref.finalize` (leak fix)
- `d9f5bf87` — broadened retry matcher + `validate_vector_list` + 3 engine wires + retry budget bump
- `69d81719` — stale `dispatcher.litellm` test removal (companion cleanup)
</artifacts>
