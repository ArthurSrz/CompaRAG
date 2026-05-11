# Architecture

**Analysis Date:** 2025-05-11

## Pattern Overview

**Overall:** Multi-layer distributed arena system with three independent comparison flows (LLM duel, MCP tool duel, ranking leaderboard) unified by a session-based blind reveal pattern.

**Key Characteristics:**
- **Blind comparison invariant:** Tool/model identities hidden until user votes
- **Equifinality fairness:** Task and goal are constant; Tool (or LLM) is the variant; Agent (Claude or LLM endpoint) is constant
- **Registry-driven dispatch:** MCP servers and LLM models loaded at startup from config
- **Per-call isolation:** Each MCP call opens its own stateless streamable HTTP session; no connection pooling
- **Normalization pipeline:** Heterogeneous RAG outputs canonicalized to `{answer, sources, confidence, latency_ms}` before display
- **Sanitization enforcement:** Server identities (names, endpoints, URLs) redacted from text and source metadata pre-display

## Layers

**FastAPI Backend (`backend/`):**
- Purpose: HTTP request routing, session orchestration, persistence coordination
- Location: `backend/main.py` entry point, three routers included: `arena/`, `tool_arena/`, `llms/`
- Contains: Route handlers, dependency injection, CORS, Prometheus metrics
- Depends on: Postgres, Redis, external LLM APIs, MCP servers
- Used by: SvelteKit frontend, client scripts, monitoring dashboards

**Arena Router (`backend/arena/`):**
- Purpose: LLM pairwise comparison (Claude vs Claude, or Claude vs Llama, etc.)
- Location: `backend/arena/router.py` (routes), `backend/arena/models.py` (Pydantic models), `backend/arena/streaming.py` (SSE streaming), `backend/arena/persistence.py` (DB writes)
- Contains: Conversation lifecycle (add_first_text → add_text → retry → react → vote → reveal)
- Depends on: `backend.llms.data` for model selection, litellm for concurrent LLM calls, session storage (Redis + Postgres)
- Used by: `/arena/*` endpoints; frontend `frontend/src/routes/duel/`

**Tool Arena Router (`backend/tool_arena/`):**
- Purpose: MCP server pairwise comparison (RAG pill vs LangChain vs LlamaIndex, etc.)
- Location: `backend/tool_arena/router.py` (routes), `backend/tool_arena/dispatcher.py` (orchestration), `backend/tool_arena/client.py` (MCP calls)
- Contains: Session creation → compare (dispatch two servers, normalize, sanitize) → vote (reveal identities, record preferences)
- Depends on: MCPDispatcher, MCPRegistry, credential system, normalizer, sanitizer, session storage, readiness probes
- Used by: `/tool-arena/*` endpoints; frontend `frontend/src/routes/tool-arena/`

**MCP Dispatch (`backend/tool_arena/dispatcher.py`):**
- Purpose: Concurrent MCP server calls with resilience and result mediation
- Location: `backend/tool_arena/dispatcher.py`
- Contains: `MCPDispatcher.dispatch()` orchestrates pool filtering, server selection (with task_type fairness), concurrent calls, normalization, sanitization
- Pattern: Pick 2 READY servers from readiness registry → open both in parallel → wrap exceptions → normalize outputs → sanitize → return MCPToolCall objects
- Key resilience: Per-server timeout (default 90s, overridable via `MCPServerConfig.timeout_seconds`), transient retry on connection errors (not timeouts), `InsufficientReadyServersError` when <2 READY servers

**MCP Client (`backend/tool_arena/client.py`):**
- Purpose: Single MCP call wrapper with credential dispatch and tool discovery
- Location: `backend/tool_arena/client.py`
- Contains: `single_mcp_call(server, task, goal, document_content)` → credential.headers_for() → streamablehttp_client session → list_tools() or named tool → call_tool() → extract TextContent → return (raw_text, duration_ms)
- Key dispatch point: Calls `credential.headers_for(server)` for auth headers (abstraction point for api_key / bearer / oauth2 implementations)
- Error handling: `MCPToolError` raised if result.isError=True; all other exceptions bubble to dispatcher

**Credential Seam (`backend/tool_arena/credential.py`):**
- Purpose: Single dispatch point for auth type branching (none / api_key / bearer / oauth2)
- Location: `backend/tool_arena/credential.py`
- Implementations:
  - `NoneCredential`: Returns `{}`
  - `ApiKeyCredential`: Reads env var, returns `{header: value}`
  - `BearerCredential`: Reads env var, returns `{"Authorization": "Bearer token"}`
  - `OAuth2Credential`: Returns `{}` for headers; exposes `provider_for(server)` for SDK's `auth=` parameter
- Caching: Per-server singleton cache via `credential_for(server)` factory
- Error hierarchy: `CredentialError` base → `CredentialRevoked`, `CredentialMisconfigured`, `CredentialUpstreamDown` for caller intent detection

**Normalizer (`backend/tool_arena/normalizer.py`):**
- Purpose: Convert heterogeneous RAG output to canonical `NormalizedEnvelope`
- Location: `backend/tool_arena/normalizer.py`
- Strategy: Try JSON parse → extract {answer, sources, confidence, latency_ms} → default missing fields → track normalized_fields to flag synthesized values
- Output: `NormalizedEnvelope` with answer, sources list (each with optional url/title/snippet/page), confidence, latency_ms, normalized_fields marker
- Downstream use: Sanitizer consumes this; router converts to CompareResponse (result_a/result_b)

**Sanitizer (`backend/tool_arena/sanitizer.py`):**
- Purpose: Redact server identifying information from text and source URLs
- Location: `backend/tool_arena/sanitizer.py`
- Functions:
  - `sanitize_output(text, servers)`: Regex-replaces server id/name/endpoint with `⟨redacted⟩` (case-insensitive)
  - `sanitize_envelope(envelope, servers)`: Strips source URLs (sets url=None), applies per-server sanitize.extra_terms and sanitize.url_patterns
- Blind invariant: All registered servers' patterns are searched (not just the two racing this round) to prevent leaked identities in user documents
- Called by: dispatcher post-normalization, before building CompareResponse

**MCPRegistry (`backend/tool_arena/registry.py`):**
- Purpose: Singleton registry of MCP servers loaded from `backend/mcp_servers.json` at startup
- Location: `backend/tool_arena/registry.py`
- Provides: `registry.get_server(id)`, `registry.server_ids`, `registry.pick_two()` (random sample without replacement)
- Validation: Errors on load → import-time failure before FastAPI accepts requests (per D-07)
- Task-type fairness: Groups servers by task_type; dispatcher samples within requested group

**Readiness Registry (`backend/tool_arena/readiness.py`):**
- Purpose: Tracks per-server health state (READY, NEEDS_REAUTH, MISCONFIGURED, UPSTREAM_DOWN, UNKNOWN)
- Location: `backend/tool_arena/readiness.py`
- Probing: Background loop runs every interval_seconds (default 60s); each probe does MCP initialize + OAuth refresh
- State machine: UNKNOWN → READY (on success) or NEEDS_REAUTH/MISCONFIGURED/UPSTREAM_DOWN (on credential/config/network errors)
- Dispatcher integration: Filters pool to READY servers only; InsufficientReadyServersError if <2 READY

**Persistence (`backend/tool_arena/persistence.py` + `backend/tool_arena/models.py`):**
- Purpose: Save tool calls and votes to Postgres; session state to Redis
- Location: `backend/tool_arena/persistence.py`, `backend/tool_arena/models.py`
- DB tables: tool_calls (one row per MCP invocation), tool_votes (one row per user vote), cron_diagnostics, cron_sentinel
- Session store: Redis key `tool_session:{session_hash}` with payload {tool_a, tool_b, voted, chosen, task, goal, llm_ids}
- Record models: `MCPToolCall` (runtime), `ToolCallRecord` (DB serialization)

**Admin Layer (`backend/tool_arena/router.py` admin routes):**
- Purpose: Operator visibility into readiness state and OAuth re-keying
- Location: `backend/tool_arena/router.py` `/admin/tool-arena/*` routes
- Endpoints:
  - `GET /admin/tool-arena/status`: Returns readiness snapshot (requires ADMIN_STATUS_TOKEN)
  - `POST /admin/tool-arena/oauth/seed`: Write refresh_token to Redis and re-probe (Phase 3)
  - `GET /admin/tool-arena/ranking/diag`: Leaderboard build diagnostics from Redis + Postgres

## Data Flow

**Tool Arena Compare Flow (Blind Phase):**

1. Client calls `POST /tool-arena/session` → returns `session_hash` (UUID)
2. Client displays task/goal/document form
3. Client calls `POST /tool-arena/compare` with task/goal/document_content/task_type
   - Router creates new session_hash and MCPDispatcher instance
   - Dispatcher filters ready servers, samples 2 (respecting task_type group if provided)
   - Both servers called concurrently via `_call_with_resilience()`
     - Each opens fresh streamablehttp_client session
     - Credential.headers_for() supplies auth headers (OAuth provider via SDK)
     - Calls tool_name (discovered via list_tools() or server.tools[0])
     - Extracts raw_text (concatenated TextContent)
     - Catches MCPToolError (isError=True) or asyncio.TimeoutError, wraps in MCPToolCall with error field
   - For success path: normalize_output(raw_text, duration_ms) → sanitize_envelope(envelope, all_servers) → sanitize_output(answer_text)
   - Persist tool calls to tool_calls table (early, don't lose data on user drop)
   - Store full session {tool_a, tool_b, task, goal, llm_ids} to Redis (includes tool_id, never sent to client)
   - Return CompareResponse with result_a/result_b (mediated_result or None), error_a/error_b (generic or None)
4. Client displays blind comparison side-by-side, user reads both results
5. Client calls `POST /tool-arena/vote` with chosen ("a"/"b"/"tie") and preferences
   - Router guards: already voted? → 403; either tool failed? → 422
   - Mark session as voted, store chosen to Redis
   - Persist ToolVoteRecord to tool_votes table (includes tool_a_id, tool_b_id, chosen, preferences)
   - Return ToolRevealResponse with tool names, descriptions, duration_ms, error (if any)
6. Client displays reveal: Tool A name/description/latency vs Tool B name/description/latency, user sees their vote outcome

**Tool Arena Reveal Flow (Post-Vote):**

- Client calls `GET /tool-arena/reveal` with session_hash header (if page reloaded post-vote)
  - Router guards: voted? → 403 if not
  - Lookup session from Redis, read tool_a_id, tool_b_id, chosen
  - Registry.get_server() for both, build ToolRevealInfo (name, description, duration_ms from session state)
  - Return ToolRevealResponse

**State Management:**

- **Blind Phase:** Session held in Redis only (tool_a/tool_b with full tool_id and raw_result); client has session_hash only
- **Vote Phase:** Session still in Redis, marked voted=True, chosen recorded; ToolVoteRecord written to Postgres (separate durable record)
- **Reveal Phase:** Session retrieved from Redis; tool identities from registry lookup
- **Data durability:** tool_calls and tool_votes written immediately (don't rely on session surviving); session=transient window (48h TTL typical Redis default)

## Key Abstractions

**MCPServerConfig:**
- Purpose: Immutable config for a single MCP server
- Loads from: `backend/mcp_servers.json` (auto-generated from `mcp_servers/*/` source)
- Fields: id, name, description, endpoint, tools (["*"] or [named]), tool_args, timeout_seconds, weight, task_type, auth (OAuth2Auth/ApiKeyAuth/BearerAuth/NoAuth), sanitize (extra_terms, url_patterns), llm_id
- Validation: Errors raised by `load_mcp_servers()` at import time

**NormalizedEnvelope:**
- Purpose: Canonical intermediate form for RAG results (post-normalize, pre-sanitize)
- Shape: {answer, sources[], confidence, latency_ms, normalized_fields[]}
- normalized_fields: List of field names that were defaulted (["sources", "confidence", "latency_ms"] if raw_text is plain text; ["latency_ms"] if JSON missing that field)
- Used by: sanitizer, router response builder

**MCPToolCall:**
- Purpose: Runtime representation of one MCP invocation result
- Fields: call_id, session_id, task, goal, tool_id, llm_id, raw_result, mediated_result, duration_ms, error, created_at
- Lifecycle: Created in dispatcher on every call (success or error); persisted to tool_calls table; included in Redis session payload
- Error handling: error field non-None indicates failure; result_a/result_b in CompareResponse becomes None, error_a/error_b becomes "Tool encountered an error"

**ToolVoteRecord:**
- Purpose: Durable record of user vote and preferences
- Fields: session_hash, tool_a_id, tool_b_id, chosen, llm_id, task, goal, timestamp, vote_goal_rating_a/b, legacy pill flags (back-compat)
- Persisted to: tool_votes table in Postgres
- Ranking input: Hourly cron job reads tool_votes, aggregates Elo scores per tool, writes to Redis leaderboard

**ReadinessRecord:**
- Purpose: Per-server health snapshot
- State: READY | NEEDS_REAUTH | MISCONFIGURED | UPSTREAM_DOWN | UNKNOWN
- Fields: server_id, state, last_error (class name + truncated repr, no secrets), last_probe_at, next_probe_at
- Lifecycle: Created on first probe; updated by background loop; snapshot() returns current list

## Entry Points

**Backend:**
- `backend/main.py`: FastAPI app, lifespan manager (probe loop startup/shutdown), CORS, Prometheus, three routers mounted
  - `lifespan()`: On startup, probe all servers with 30s budget; spawn background re-probe task
  - Shutdown: Cancel re-probe task

**MCP Servers:**
- `mcp_servers/rag_pill/server.py`: FastMCP lifespan (initialize engines + PillRegistry), `/health`, `/pills`, `rag_pill_query` tool
- `mcp_servers/langchain_rag/`: Single LangChain pipeline (index on first call, reuse)
- `mcp_servers/llamaindex_rag/`: Single LlamaIndex pipeline (same pattern)

**Frontend:**
- `frontend/src/routes/tool-arena/+page.svelte`: Main page, forms, API calls, state management
- `frontend/src/routes/tool-arena/components/`: UI components (CompareCard, VotePanel, RevealScreen, etc.)
- `frontend/src/routes/tool-arena/leaderboard/`: Leaderboard viewer (reads from `/tool-arena/leaderboard` endpoint)

## Error Handling

**Strategy:** Fail fast with structured errors; never silently degrade

**Patterns:**

- **MCP timeout (asyncio.TimeoutError):** No retry (doubling wait time unhelpful); wrapped in MCPToolCall.error; dispatcher logs warning; router returns error_a/error_b="Tool encountered an error"
- **MCP connection error (httpx.ConnectError, etc.):** Up to MCP_CALL_RETRIES retries (default 1) with exponential backoff (2^attempt sec); if all fail, wrapped in MCPToolCall.error
- **MCP protocol error (mcp.McpError):** Wrapped in MCPToolCall.error; dispatcher logs
- **MCPToolError (result.isError=True):** Raised by client; caught and wrapped by dispatcher
- **Credential errors:**
  - `CredentialRevoked`: Readiness probe marks server NEEDS_REAUTH; admin must re-key via `/admin/tool-arena/oauth/seed`
  - `CredentialMisconfigured`: Marks server MISCONFIGURED; fix env var or config
  - `CredentialUpstreamDown`: Marks server UPSTREAM_DOWN; transient, will recover
- **InsufficientReadyServersError:** Raised by dispatcher when <2 READY servers; router catches and returns 503 with `{"error": "tool_unavailable"}`
- **Session not found:** Router dependency returns 400 "Missing session hash" or 400 "Conversations couldn't be found"
- **Already voted (Pitfall 2):** Router returns 403 "Already voted"
- **At least one tool failed (Pitfall 6):** Router returns 422 "At least one tool failed, vote not possible"

## Cross-Cutting Concerns

**Logging:** Structured JSON via `logging.getLogger("languia")`; key events include:
- MCP calls: `mcp call server={} tool={} raw_len={} duration_ms={}`
- Dispatch: `dispatcher: insufficient READY servers (have={}, need=2)`
- Errors: `MCP call to {} failed: {}: {}`

**Validation:** Pydantic models for all request/response shapes (CompareRequest → CompareResponse, etc.); enum constraints on task_type (Literal["summary", "qa", "extraction"])

**Authentication (OAuth/API key):** Handled by credential module; no tokens in logs; Phase 3 admin re-key endpoint for OAuth refresh_token refresh

**Rate limiting:** Arena router has IP-based rate limiting for expensive models (prevent spam of costly LLM tiers); tool arena has no rate limit (MCP servers control concurrency)

**Blind invariant enforcement:**
- Server identity never in CompareResponse (only result_a, result_b, error messages)
- Tool names/endpoints sanitized from answer text before display
- Source URLs stripped from envelope before returning to client
- Reveal only on POST /vote (guards prevent pre-vote reveal)
