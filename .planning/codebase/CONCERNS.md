# Codebase Concerns

**Analysis Date:** 2025-05-11

## Critical Issues

### Dispatcher Pool=2 Footgun (Weighted Sampling Bypass)

**Issue:** When the pool has exactly 2 servers, weighted sampling is bypassed entirely.

**Files:** `backend/tool_arena/dispatcher.py:133-145`

**Problem:**
```python
if len(pool) == 2:
    server_a, server_b = pool[0], pool[1]  # Direct assignment, ignores weights!
else:
    # ... weighted sampling with renormalization
```

When there are more than 2 servers in a task_type group, the weighted sampling logic correctly respects per-server weights (e.g., `weight=2.0` for a new contestant to collect more votes). However, when a pool has exactly 2 servers:
- **Current behavior:** Server A and B are always picked in order, 100% of the time
- **Expected behavior:** Respect the weight ratio (e.g., if A has weight=1.0 and B has weight=2.0, B should be in the first slot ~67% of the time)

**Impact:** High. Users vote on results; skewed sampling due to weights means some configurations never see the intended proportional representation. A server with `weight=2.0` deployed into a 2-server pool sees no benefit.

**Root cause:** Fast-path optimization that assumes "if exactly 2, no randomization needed" without accounting for weights.

**Fix approach:**
1. Remove the `if len(pool) == 2` special case
2. Let the weighted sampling logic handle all cases uniformly
3. Add a test that verifies weight ratios in 2-server pools match expected proportions

**Test coverage gap:** No test verifies that weights are respected when pool size is exactly 2.

---

### rag-pill Railway Service Not Auto-Deployed

**Issue:** Pushing to `develop` does NOT auto-deploy the rag-pill MCP server.

**Files:** Railway service configuration (not in git); manual deployment required via `railway up --service rag-pill`

**Problem:**
- Backend, frontend, and ranking cron auto-deploy on git push (configured in Railway dashboard)
- rag-pill is a separate Railway service connected to the same repo but NOT wired to auto-deploy
- Developers must manually run `railway up --service rag-pill` after pushing changes to `mcp_servers/rag_pill/`
- Silent failure mode: the change deploys to code but the old container still runs

**Impact:** High. Any bug fix, feature, or engine improvement to rag-pill stays in development until someone explicitly deploys. Users hit old behavior with new code on the repo.

**Why it exists:** rag-pill is a long-running service with resource initialization; auto-deploy to a backend Dockerfile would require separate Dockerfile + config, and Railway's service orchestration treats each service independently.

**Fix approach:**
1. Add auto-deploy trigger to Railway dashboard for rag-pill service on git push
2. Document the manual deploy requirement in CLAUDE.md / Makefile (already done in CLAUDE.md)
3. Add a GitHub Actions check that warns if `mcp_servers/rag_pill/` changed but rag-pill was not deployed

**Workaround:** Use CI/CD to auto-trigger Railway deploys; currently done manually.

---

## Deployment & Infrastructure

### Ranking Cron Service Must Use Separate Dockerfile

**Issue:** The ranking cron service is wired to `docker/Dockerfile.cron` rather than reusing the backend Dockerfile.

**Files:** `railway.cron.toml:6, docker/Dockerfile.cron`

**Why it matters:** Railway's `startCommand` override does NOT reliably replace `["sh", "-c", "..."]` form CMD directives. Reusing the backend Dockerfile (which ends with `CMD ["sh", "-c", "uvicorn ..."]`) would silently start the web server instead of running the ranking script.

**Current state:** Dedicated Dockerfile correctly ends with `CMD [...ranking_script...]`, so cron works as intended.

**Risk:** If someone tries to "optimize" by removing `Dockerfile.cron` and reusing the backend image, the cron will become a second backend instance, silently dropping ranking jobs.

**Mitigation:** The comment block at the top of `railway.cron.toml` documents this footgun. **No code change needed, but vigilance required during refactoring.**

---

## OAuth & Authentication

### OAuth Tokens Stored Only in Redis; No Env-Var Bootstrap

**Issue:** OAuth refresh_tokens are stored only in Redis and in `.oauth_tokens/` on disk (local dev fallback). There is NO `{SERVER_ID}_REFRESH_TOKEN` env-var bootstrap path.

**Files:** `backend/tool_arena/auth.py:1-120`, `backend/tool_arena/oauth_setup.py`, `backend/tool_arena/config.py:28-35`

**Why this changed:** Previous versions allowed seeding refresh_tokens via env vars (e.g., `CLARIFEYE_REFRESH_TOKEN`). This was **removed in Phase 3 (ADR-0001)** because:
- When Redis is wiped (e.g., during a redeploy), the env var is read and re-seeds a now-revoked refresh_token
- The upstream MCP server's token rotation invalidates that stale token
- Silent auth failures result

**Current flow:**
1. Developer runs `scripts/auth_setup.py <server_id>` locally (opens browser, captures OAuth callback)
2. Tokens are written to `.oauth_tokens/<server_id>.json` on disk
3. `POST /admin/tool-arena/oauth/seed` endpoint accepts tokens and writes to Redis
4. Startup probe runs `prewarm_oauth_provider` to validate tokens and refresh if needed

**Risks:**
- **Token loss on Redis flush:** If Redis is cleared without re-keying, OAuth servers are in NEEDS_REAUTH until manually re-seeded
- **No automated re-key on deploy:** Unlike API keys (which can be rotated env-side), OAuth requires browser interaction
- **Admin endpoint security:** `POST /admin/tool-arena/oauth/seed` is protected by `ADMIN_STATUS_TOKEN` env var, but if that token leaks, an attacker can inject arbitrary OAuth tokens

**Documentation:** `CLAUDE.md` in the project root documents the re-key flow. The concern is that it requires **manual human intervention** (browser auth flow).

**Fix approach:**
- Phase 4+: Implement a background OAuth refresh loop that auto-renews tokens before expiry
- Consider a "token snapshot" feature that exports/imports tokens safely for disaster recovery
- Document Redis flush procedures to include OAuth re-keying steps

---

### Clarifeye OAuth Token Refresh Concurrency

**Issue:** Multiple replicas of the backend could attempt to refresh the same OAuth token simultaneously.

**Files:** `backend/tool_arena/auth.py:121-195`

**Mitigation:**
- A Redis distributed lock (`oauth_refresh_lock:{server_id}`) is acquired before refresh
- Only one replica enters the refresh flow; others wait
- Token is stored with `set_tokens()` call, which updates Redis

**Status:** Implemented but untested at scale. Lock timeout is **not explicitly set**, relying on Redis's default behavior. If a replica crashes while holding the lock, the lock persists until it times out (potentially blocking all future refreshes).

**Recommendation:** Set an explicit lock TTL in `backend/tool_arena/auth.py:181` (e.g., 30 seconds max, with renewal if refresh is still in progress).

---

## RAG Engines & Embedding Handling

### Asymmetric Embedding Validation Across Engines

**Issue:** Only the Haystack engine validates OpenRouter's degraded embedding responses. LangChain and LlamaIndex engines lack the same validation.

**Files:**
- `mcp_servers/rag_pill/engines/haystack_engine.py` — uses embedding validator
- `mcp_servers/rag_pill/engines/langchain_engine.py:50-55` — NO validator
- `mcp_servers/rag_pill/engines/llamaindex_engine.py:43-48` — NO validator
- `mcp_servers/rag_pill/providers/embedding_validator.py` — only applied to Haystack

**Problem:** OpenRouter sometimes returns 200 OK with `embedding=None` when degraded. Haystack detects this via `validate_document_embeddings()` and `validate_query_embedding()`, converting it to a `ValueError` that the retry wrapper catches. LangChain and LlamaIndex silently pass None into their retrievers, causing `TypeError: 'NoneType' object is not subscriptable`.

**Impact:** Medium. Rare under normal OpenRouter conditions, but under load or regional outages, LangChain/LlamaIndex fail while Haystack retries gracefully.

**Fix approach:**
1. Extract the embedding validators to a shared module (already at `mcp_servers/rag_pill/providers/embedding_validator.py`)
2. Call validators immediately after `embeddings.embed_query()` / `embeddings.embed_documents()` in langchain_engine.py and llamaindex_engine.py
3. Add integration tests that mock OpenRouter returning None embeddings

---

### Block Sync Calls in Async Paths (Proper but Worth Monitoring)

**Status:** Current implementation correctly uses `asyncio.get_event_loop().run_in_executor()` for blocking operations:

**Files:**
- `mcp_servers/rag_pill/engines/langchain_engine.py:70-71` — FAISS indexing in executor
- `mcp_servers/rag_pill/engines/llamaindex_engine.py:63-64` — LlamaIndex indexing in executor
- `mcp_servers/rag_pill/engines/haystack_engine.py:81, 110` — Haystack operations in executor

**No immediate risk**, but note: these operations may block the event loop's thread pool if many requests arrive simultaneously. Monitor with APM (Sentry) to detect indexing latency spikes during traffic peaks.

---

## Frontend Constraints

### TaskType Restricted to 'summary' Only

**Issue:** The frontend exposes only `'summary'` as a task type, while the backend accepts `'summary' | 'qa' | 'extraction'`.

**Files:** `frontend/src/routes/tool-arena/components/ToolArenaForm.svelte:32`

```typescript
type TaskType = 'summary'

const taskTypes: { value: TaskType; ... }[] = [
  { value: 'summary', label: ..., prompt: ..., goalText: ... }
]
```

**Rationale:** Lines 27-31 state that QA and extraction are "hidden until end-to-end validated." Backend Literal stays permissive (`| 'qa' | 'extraction'`) so re-enabling either is a frontend-only change.

**Current state:** This is **intentional**. All three task types are technically supported by the backend and some engines, but the UI gatekeeping ensures only validated flows reach users.

**Risk:** Low. No data loss or security issue. Users cannot trigger untested code paths.

**Future work:** Once QA and extraction are end-to-end tested, change line 32 to:
```typescript
type TaskType = 'summary' | 'qa' | 'extraction'
```
and update `taskTypes` array to include the other two entries.

---

## Architecture & Design

### tool_arena/config.py Deliberately Decoupled from backend.config

**Issue:** `backend/tool_arena/config.py` explicitly does NOT import from `backend.config` or `backend.arena`.

**Files:** `backend/tool_arena/config.py:1-8` (docstring), `backend/tool_arena/config.py:7`

**Rationale:** Testing constraint. The config module loads MCP server definitions from JSON and validates them with Pydantic. If it imported psycopg2 / Redis dependencies from `backend.config`, tests would require a running database.

**Current design:** `config.py` is a pure Pydantic module with zero I/O dependencies. Tests import and instantiate it directly.

**No action needed**, but be aware: if you need to add database-backed configuration (e.g., reading MCP server URLs from the database), you **cannot** do it in `config.py` without breaking test isolation. Create a separate layer for database-driven overrides.

---

## Caching & Performance

### Cache-Control Headers on Documents Endpoints

**Issue:** Document endpoints return cache headers but with long stale-while-revalidate windows.

**Files:** `backend/tool_arena/documents_router.py:24, 44, 60`

```python
_DOCUMENTS_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"
```

**Settings:**
- `max-age=3600` — Document is fresh for 1 hour
- `stale-while-revalidate=86400` — Browser may use stale copy for 24 hours if backend is unavailable

**Implications:**
- Document content updates take up to 24 hours to propagate to clients
- In production, Redis caching may mask stale content issues

**Risk:** Low for static documents. Higher if documents are updated frequently (rare in the arena use case).

**Recommendation:** Monitor document freshness in analytics. If users report stale content, reduce `stale-while-revalidate` to 3600 (1 hour).

---

## Observability & Logging

### Sparse TODO/FIXME Comments Across Codebase

**Issue:** Many TODO/FIXME comments indicate areas of uncertainty or technical shortcuts.

**High-priority TODOs:**
- `backend/logger.py:57` — "TODO: remove IP? (privacy concern)" — IP addresses are logged; consider GDPR implications
- `backend/arena/persistence.py:78, 108, 180, 189` — Multiple FIXME comments about database error handling consistency
- `backend/arena/persistence.py:331, 483, 689, 694` — "FIXME: not sure what serialization is needed" — Uncertain data structure mappings

**Medium-priority:**
- `backend/arena/router.py:83` — "FIXME raise different errors depending on problem" — Generic error handling
- `backend/llms/data.py:139, 171, 187` — Multiple FIXMEs around model availability and sanitization

**Low-priority (nice-to-have):**
- `backend/llms/utils.py:158, 163` — "TODO: Contribute custom model data back to ecologits project"
- `frontend/src/lib/models.ts:63` — "FIXME required?" — Type annotation uncertainty

**Action:** No immediate risk, but these should be tracked in a separate tech debt backlog. Consider using a linter rule to flag TODOs in CI/CD.

---

## Security Considerations

### IP Logging (Privacy Concern)

**Issue:** IP addresses are logged in request processing.

**Files:** `backend/logger.py:57`

```python
# TODO: remove IP? (privacy concern)
```

**Risk:** Medium. Depending on jurisdiction (GDPR, CCPA, etc.), logging IPs may require explicit user consent or privacy policy documentation.

**Current state:** TODO indicates this is a known concern but not yet addressed.

**Recommendation:**
1. Review privacy policy; confirm whether IP logging is disclosed
2. If not disclosed, add config flag to disable IP logging (e.g., `LOG_IPs=false` by default)
3. Update CLAUDE.md with privacy guidelines for future logging

---

### Credential Error Redaction

**Status:** Implemented correctly.

**Files:** `backend/tool_arena/readiness.py:95-107`

```python
def _scrub_error(exc: BaseException) -> str:
    """Return ``ClassName: <first 200 chars of repr>`` with no secrets."""
    # ... truncates to 200 chars, no token bodies included
```

The credential module uses typed errors that don't include raw token bodies. Additional defense-in-depth truncation ensures admin responses don't leak large token payloads. **No concern here.**

---

## Error Handling & Resilience

### MCP Tool Errors Properly Surfaced

**Issue:** When an MCP tool returns `isError=True`, it's raised as `MCPToolError` rather than silently treated as content.

**Files:** `backend/tool_arena/client.py:127-132`

**Current implementation:** Correct. Errors are logged and the dispatcher's exception path converts them to `MCPToolCall` with an `error` field, which the reveal endpoint exposes.

**Test coverage:** Good. Tests validate error handling across dispatches.

---

## Long-Running Operations & Timeouts

**Status:** Well-covered with configurable timeouts.

**Files:** `backend/tool_arena/dispatcher.py:50` — `MCP_CALL_TIMEOUT = 90` (default)

**Timeouts in place:**
- Per-server override: `server.timeout_seconds` (optional)
- OAuth pre-warm: `OAUTH_PREWARM_TIMEOUT = 20` seconds
- Readiness probe: `30` seconds default
- Dry-run endpoint: `_DRY_RUN_TIMEOUT = 30` seconds

**Risk:** Low. All async I/O operations have explicit timeouts. No unbounded waits detected.

**Note:** `MCP_CALL_TIMEOUT` default was raised from 30s to 90s to support agentic tools (Clarifeye's multi-step reasoning). Monitor dashboard to ensure 90s is still appropriate.

---

## Test Coverage Gaps

### Dispatcher Weighted Sampling Not Tested with Exactly 2 Servers

**Issue:** No test verifies that weight ratios are respected when pool size is exactly 2.

**Files:** `backend/tool_arena/tests/test_dispatcher.py` (no test for this case)

**Expected test:**
```python
async def test_weighted_sampling_with_exactly_two_servers():
    """Verify pool=2 respects weights, not just returns pool[0], pool[1]."""
    server_a = MCPServerConfig(..., id="a", weight=1.0)
    server_b = MCPServerConfig(..., id="b", weight=2.0)
    # Dispatch N times, verify server_b appears first ~67% of the time
```

**Recommendation:** Add this test to catch regressions if the fast-path special case is ever reintroduced.

---

### Embedding Validation Not Tested for LangChain/LlamaIndex

**Issue:** Test suite only covers Haystack embedding validation, not the other engines.

**Files:** `mcp_servers/rag_pill/tests/` — tests for rag_pill exist, but embedding validator tests are Haystack-specific

**Recommendation:** Add integration tests that mock OpenRouter returning None embeddings and verify all engines retry gracefully.

---

## Git Practices (Documented Incident)

### Never Use `git stash` / `git stash pop` to Park Work

**Issue:** A previous incident where `git stash pop` collided with a pre-existing stash, causing reverted edits.

**Files:** Documented in user instructions; not a code issue

**Incident:** During a session, developer used `git stash` to park changes, later ran `git stash pop`, which collided with another stash. Result: lost `documents_router.py` edits, had to reseat `pypdf`/`python-docx` dependencies.

**Mitigation:** Use `git worktree add ../tmp HEAD` instead to create an isolated checkout for probing pre-existing issues. **Document in CONTRIBUTING.md or project README.**

---

## Synthetic Monitor Hook (Known but Monitored)

**Issue:** Synthetic monitoring script has a kill-switch that may be enabled accidentally.

**Files:** `scripts/synthetic_monitor.py`, `~/.claude/logs/comparag-monitor.log`

**Current state:** A cron job periodically runs synthetic tests against the arena. If `COMPARAG_SYNTHETIC_DISABLED=1` is set, it stops.

**Risk:** Low. This is a documented feature (see project memory). A GitHub issue (`synthetic-monitor`) tracks any failures. No action needed, but be aware if synthetic test results suddenly drop.

---

## Missing Features & Known Limitations

### No Automated OAuth Token Refresh Before Expiry

**Issue:** Tokens are refreshed on-demand (at request time) but not proactively before expiry.

**Files:** `backend/tool_arena/auth.py:132-195`

**Scenario:**
1. OAuth token expires at 2:00 PM
2. User makes a request at 2:01 PM
3. Refresh happens, brief latency added to that request
4. If many users hit simultaneously, multiple refresh attempts occur

**Improvement:** Implement a background job that refreshes tokens 5 minutes before expiry, reducing user-facing latency.

**Priority:** Low. Current on-demand refresh is functional; improvement is a UX optimization.

---

### No Distributed Token Validation Across Replicas

**Issue:** Each backend replica independently validates its OAuth tokens on startup (prewarm phase).

**Files:** `backend/tool_arena/auth.py:440-490`

**Scenario:** If two replicas start simultaneously and both attempt OAuth handshakes, brief token inconsistency may occur.

**Mitigation:** Current code already uses a distributed lock for refresh. However, the startup prewarm does not coordinate across replicas.

**Risk:** Low. Token cache is stored in Redis; worst case is a brief double-refresh during deployment. No data loss or auth bypass.

**Priority:** Low. Acceptable tradeoff for simplicity.

---

## Summary Table

| Area | Issue | Severity | Status |
|------|-------|----------|--------|
| Dispatcher | pool=2 weighted sampling bypassed | High | Unfixed |
| Deployment | rag-pill no auto-deploy | High | Documented, requires manual trigger |
| Infrastructure | Cron Dockerfile separation | Medium | Correct, requires vigilance |
| OAuth | Tokens only in Redis, no env-var bootstrap | Medium | Intentional design, documented |
| OAuth | Refresh concurrency lock | Low | Implemented, could add TTL |
| RAG | Asymmetric embedding validation | Medium | Haystack only, others at risk |
| Frontend | TaskType limited to summary | Low | Intentional, documented gate |
| Logging | IP addresses logged | Medium | Privacy concern flagged, not resolved |
| Caching | Documents stale-while-revalidate 86400s | Low | Functional, monitor freshness |
| Testing | pool=2 sampling not tested | Medium | Test gap, easy fix |
| Git | stash/pop collision risk | Low | Documented incident, mitigation provided |

