---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: Document Context Selection
status: Active
stopped_at: Completed 14-engine-hardening 14-01-PLAN.md (Task 6 pending — Railway build verify)
last_updated: "2026-05-13T09:01:00.000Z"
progress:
  total_phases: 5
  completed_phases: 1
  total_plans: 3
  completed_plans: 2
---

# Project State

## Current Position

- **Phase:** 14-engine-hardening
- **Plan:** 01 (5 of 6 tasks shipped; Task 6 — prod verify — pending Railway build of d9f5bf87)
- **Status:** Active — phase 13 (QA Task Enablement) still in flight; phase 14 inserted to track today's hardening burst.

## Progress

Phase 11 document library fully complete. Both document endpoints wired with Cache-Control headers. Requirements DOC-02 and DOC-03 satisfied.

## Decisions

- Document list endpoint returns DocumentSummary (no content) for lean catalogue responses
- Document detail endpoint returns DocumentDetail with content or 404
- Cache-Control: public, max-age=3600, stale-while-revalidate=86400 on both endpoints (CDN-appropriate)
- 404 detail message is generic "Document not found" (per spec, not interpolated with doc_id)
- Response parameter injection (not raw Response return) preserves FastAPI Pydantic serialization
- Minimal test app pattern for router integration tests to avoid psycopg2/Redis blocking imports

## Out-of-Phase Work

### 2026-05-11 — Frontend task-type restriction (two passes)
- **Pass 1 (commit `e0442485`):** Removed `'extraction'` because no server in `mcp_servers.json` declares it. Frontend `TaskType` reduced from `{summary, qa, extraction}` → `{summary, qa}`. Vercel-deployed and confirmed via SSR HTML poll.
- **Pass 2 (this commit):** User reported QA hasn't been end-to-end validated either. `TaskType` further reduced to `{summary}`. The 1-option dropdown is hidden entirely (`{#if taskTypes.length > 1}` guard) so users see a clean form instead of a degenerate select. The `requiresDocument` comparison against `'qa'` is preserved so re-enabling QA is a one-line change.
- **Scope:** Frontend only — backend `CompareRequest.task_type` Literal stays permissive.
- **Validation:** Production UI smoke test confirmed pre-fix that haystack engine no longer surfaces `NoneType is not subscriptable`. 30-iteration probe in progress (`/tmp/arena_30runs_report.md`).

### 2026-05-11 — Haystack engine None-embedding fix
- **Why:** Beta-user surfaced `TypeError: 'NoneType' object is not subscriptable` from haystack when OpenRouter returns degraded embedding payloads (200 OK with `embedding=None` instead of empty `data`).
- **What:** New `providers/embedding_validator.py` converts None payloads into the retry-marker `ValueError`; wired at both call sites in `engines/haystack_engine.py`. Unit + integration regression tests added.
- **Shipped:** Commit `071fd63e` on `develop`; `rag-pill` redeployed via `railway up --service rag-pill` (banner observed at 06:37:29 UTC).
- **Follow-up:** Symmetric fix delivered in Phase 14 (see below) — langchain, llamaindex, and chroma_baseline now have the same boundary validator.

### 2026-05-13 — Phase 14: Engine Hardening (chromadb race, leak, NoneType subscript)
- **Why:** Production screenshot 2026-05-12 showed both Tool A and Tool B failing on `chroma_baseline` with `'RustBindingsAPI' object has no attribute 'bindings'` and `KeyError: 'ephemeral'`. User then reported `'NoneType' object is not subscriptable` on `haystack` (post-retry-budget exhaustion path).
- **What:**
  - `e579b024` — chromadb 1.x EphemeralClient race: module-level singleton + asyncio.Lock to serialize first-touch.
  - `5759bd8c` — chromadb collection leak on IndexCache eviction: `_CollectionHandle` with `weakref.finalize(handle, client.delete_collection, name)`.
  - `d9f5bf87` — broadened `_is_empty_embedding_data_error` to message-substring across any exception class with `__cause__`/`__context__` chain walking; added `validate_vector_list` and wired it into langchain (pre-embed → `FAISS.from_embeddings`), llamaindex (probe `Settings.embed_model.get_text_embedding_batch`), and chroma (subclassed `OpenAIEmbeddingFunction`); bumped default `RAG_PILL_EMBEDDING_RETRIES` 2→4 (31s window).
  - `69d81719` — companion: removed stale `dispatcher.litellm` test; covered by `test_dispatch_passes_identical_task_goal_to_both`.
  - Modernization sweep: 6× `asyncio.get_event_loop()` → `asyncio.get_running_loop()` (3.14 readiness).
- **Tests:** 359 pass / 0 fail (baseline 243 + 108 + 8 new validator/retry coverage).
- **Verified (in prod):** chromadb race fix — 10-round browser-harness stress test against https://comparag.vercel.app/tool-arena returned 10/10 clean.
- **Pending (in prod):** NoneType-subscript fix — Railway building `d9f5bf87` server-side; stress test to follow.
- **Workflow change:** rag-pill now deploys via `git push` to develop, not `railway up --service rag-pill` (the CLI's chunked upload times out reliably from this machine — curl proves the endpoint is reachable in 260ms; the long-lived multipart stream is what fails). Documented in `CompaRAG/CLAUDE.md` and the corresponding memory entry.

## Last Session

- **Stopped at:** Completed 11-document-library 11-02-PLAN.md (with Cache-Control and test_documents_endpoints.py)
- **Timestamp:** 2026-04-20T11:45:00Z

## Performance Metrics

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 11-document-library | 02 | 15min | 2 | 3 |
