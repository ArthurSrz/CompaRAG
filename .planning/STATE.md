---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: Document Context Selection
status: Active
stopped_at: Completed 11-document-library 11-02-PLAN.md
last_updated: "2026-05-11T06:45:00.000Z"
progress:
  total_phases: 2
  completed_phases: 1
  total_plans: 2
  completed_plans: 2
---

# Project State

## Current Position

- **Phase:** 11-document-library
- **Plan:** 02 (complete)
- **Status:** Active — ready for Phase 12 (Context Injection)

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
- **Follow-up:** Symmetric fix candidate for `langchain_engine.py` and `llamaindex_engine.py`.

## Last Session

- **Stopped at:** Completed 11-document-library 11-02-PLAN.md (with Cache-Control and test_documents_endpoints.py)
- **Timestamp:** 2026-04-20T11:45:00Z

## Performance Metrics

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 11-document-library | 02 | 15min | 2 | 3 |
