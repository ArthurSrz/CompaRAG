# Codebase Structure

**Analysis Date:** 2025-05-11

## Directory Layout

```
CompaRAG/
├── backend/                          # FastAPI application (Python 3.13, uv workspace)
│   ├── main.py                       # FastAPI app entry point, routers, lifespan
│   ├── config.py                     # Global settings (DB, Redis, country portals, objectives)
│   ├── logger.py                     # Structured logging setup
│   ├── errors.py                     # Custom exception hierarchy
│   ├── sentry.py                     # Error tracking initialization
│   ├── cors_utils.py                 # CORS origin builder
│   ├── arena/                        # LLM duel module
│   │   ├── router.py                 # Routes: /arena/add_first_text, /add_text, /retry, /react, /vote, /reveal
│   │   ├── models.py                 # Pydantic: Conversations, Conversation, UserMessage, AssistantMessage, etc.
│   │   ├── streaming.py              # SSE streaming (stream_comparison_messages)
│   │   ├── persistence.py            # DB writes: record_conversations, record_vote, record_reaction
│   │   ├── session.py                # Session storage and rate limiting
│   │   ├── reveal.py                 # Reveal data builder (get_reveal_data, get_chosen_llm)
│   │   ├── litellm.py                # LiteLLM concurrent model calls
│   │   └── spam_detection.py         # Input validation
│   ├── tool_arena/                   # MCP tool duel module
│   │   ├── router.py                 # Routes: /tool-arena/session, /compare, /vote, /reveal, /leaderboard, /dry-run
│   │   ├── dispatcher.py             # MCPDispatcher (orchestrate two concurrent MCP calls)
│   │   ├── client.py                 # single_mcp_call (wrapper for one MCP invocation)
│   │   ├── normalizer.py             # normalize_output → NormalizedEnvelope
│   │   ├── sanitizer.py              # sanitize_output, sanitize_envelope (redact identities)
│   │   ├── credential.py             # Credential protocol + implementations (none, api_key, bearer, oauth2)
│   │   ├── registry.py               # MCPRegistry (singleton, loads mcp_servers.json)
│   │   ├── readiness.py              # ReadinessRegistry, probe_server, readiness_probe_loop
│   │   ├── config.py                 # MCPServerConfig, load_mcp_servers (self-contained, no arena imports)
│   │   ├── auth.py                   # OAuth provider factory (CompaRAGOAuthProvider, token refresh)
│   │   ├── oauth_setup.py            # OAuth initialization
│   │   ├── models.py                 # Pydantic: MCPToolCall, ToolCallRecord
│   │   ├── persistence.py            # DB writes: save_tool_call_to_db, save_tool_vote_to_db
│   │   ├── session.py                # Redis session store for tool arena (separate from arena)
│   │   ├── documents_router.py       # Routes: /tool-arena/documents, /tool-arena/documents/{id}
│   │   ├── tests/                    # Unit tests for normalizer, sanitizer, credential, readiness, etc.
│   │   └── migrations/               # DB schema migrations
│   ├── llms/                         # LLM metadata module
│   │   ├── router.py                 # Route: GET /models
│   │   ├── data.py                   # LLM selection logic (pick_two by mode)
│   │   ├── models.py                 # Pydantic: LLMData, LLMDataEnabled
│   │   ├── utils.py                  # Consumption tracking
│   │   └── data/                     # JSON files: model definitions per country portal
│   ├── utils/                        # Shared utilities
│   │   ├── user.py                   # get_ip, get_matomo_tracker_from_cookies
│   │   └── countries.py              # CountryPortal, get_country_portal_count
│   └── tests/                        # Backend tests
│
├── frontend/                         # SvelteKit application (Node.js, Vercel deployment)
│   ├── src/
│   │   ├── routes/
│   │   │   ├── duel/                 # LLM arena (not in this doc scope)
│   │   │   │   └── +page.svelte
│   │   │   ├── tool-arena/           # MCP tool arena
│   │   │   │   ├── +page.svelte      # Main page: form, blind compare, vote, reveal
│   │   │   │   ├── components/       # UI components
│   │   │   │   │   ├── CompareCard.svelte      # Side-by-side result card
│   │   │   │   │   ├── VotePanel.svelte       # Vote selection (a/b/tie)
│   │   │   │   │   ├── RevealScreen.svelte    # Tool identity reveal
│   │   │   │   │   ├── FileUpload.svelte      # Document upload
│   │   │   │   │   └── ...
│   │   │   │   └── leaderboard/      # Rankings page
│   │   │   │       └── +page.svelte
│   │   │   ├── metrics/              # Dashboard (not in scope)
│   │   │   ├── product/              # Landing page (not in scope)
│   │   │   ├── +layout.svelte        # Root layout
│   │   │   ├── +layout.ts            # Root layout hooks
│   │   │   └── +error.svelte         # Error boundary
│   │   ├── lib/
│   │   │   ├── components/dsfr/      # French government design system (DSFR) components
│   │   │   ├── i18n/                 # Paraglide i18n setup (fr, da, sv, et, lt)
│   │   │   ├── api/                  # Fetch wrappers (arena.ts, tool_arena.ts)
│   │   │   └── ...
│   │   └── app.css                   # Global styles
│   ├── locales/                      # i18n locale files (*.json per language)
│   ├── e2e/                          # Playwright end-to-end tests
│   │   ├── demo.test.ts              # LLM arena flow
│   │   └── modeles.test.ts           # Model leaderboard
│   ├── playwright.config.ts          # Playwright config
│   ├── svelte.config.js              # SvelteKit + Vercel adapter
│   ├── tailwind.config.ts            # Tailwind CSS config
│   ├── package.json                  # Node dependencies
│   └── package-lock.json
│
├── mcp_servers/                      # MCP server implementations (Docker, Railway)
│   ├── start_servers.sh              # Script to spawn all servers locally
│   ├── rag_pill/                     # Registry-driven multi-engine RAG dispatcher
│   │   ├── server.py                 # FastMCP lifespan, @mcp.tool rag_pill_query
│   │   ├── registry.py               # PillRegistry (loads pills/*.yaml, maps to engines)
│   │   ├── schemas.py                # Pydantic: Pill, PillConfig
│   │   ├── cache.py                  # IndexCache (in-memory, max 32 entries)
│   │   ├── retry.py                  # execute_with_embedding_retry (retry on None embeddings)
│   │   ├── engines/                  # Multi-framework RAG engines
│   │   │   ├── base.py               # RAGEngine abstract base (SUPPORTS, run method)
│   │   │   ├── langchain.py          # LangChainEngine
│   │   │   ├── llamaindex.py         # LlamaIndexEngine
│   │   │   ├── haystack.py           # HaystackEngine
│   │   │   ├── txtai.py              # TxtaiEngine
│   │   │   └── chroma.py             # ChromaBaselineEngine
│   │   ├── pills/                    # YAML definitions of RAG configurations
│   │   │   ├── default_summary.yaml
│   │   │   ├── default_qa.yaml
│   │   │   └── ...
│   │   ├── providers/                # Shared LLM/embedding clients
│   │   │   ├── llm.py                # OpenRouterLLM wrapper
│   │   │   ├── embeddings.py         # EmbeddingConfig, provider selection
│   │   │   ├── embedding_validator.py # Retry marker for None-valued embeddings
│   │   │   └── ...
│   │   ├── strategies/               # RAG strategies (retrieval + generation patterns)
│   │   ├── tests/                    # rag_pill unit tests
│   │   ├── Dockerfile                # Railway Docker image for rag_pill service
│   │   ├── railway.toml              # Railway service config
│   │   ├── requirements.txt          # Installs all engine requirements
│   │   └── requirements-{engine}.txt # Per-engine dependencies
│   │
│   ├── langchain_rag/                # Single LangChain pipeline MCP server
│   │   ├── main.py                   # FastMCP + streamable HTTP
│   │   ├── rag.py                    # RAG pipeline (index once, reuse)
│   │   └── requirements.txt
│   │
│   ├── llamaindex_rag/               # Single LlamaIndex pipeline MCP server
│   │   ├── main.py                   # FastMCP + streamable HTTP
│   │   ├── rag.py                    # RAG pipeline
│   │   └── requirements.txt
│   │
│   ├── corpus/                       # Document corpus (shared across MCP servers)
│   │   └── *.pdf, *.txt              # Test/demo documents
│   │
│   └── mcp_servers.external.json     # External MCP servers (Clarifeye, etc.)
│
├── utils/                            # Utility modules (Python poetry + separate workflows)
│   ├── ranking/                      # Leaderboard builder (cron job)
│   │   ├── run.py                    # Read tool_votes from Postgres, compute Elo, write Redis
│   │   └── config.py
│   ├── ranking_methods/              # Ranking algorithms (separate Poetry env)
│   │   ├── pyproject.toml
│   │   ├── tests/
│   │   └── ...
│   ├── storage/                      # DB and Redis clients
│   │   ├── db.py                     # db_cursor context manager (psycopg2)
│   │   ├── redis.py                  # get_redis_client
│   │   └── ...
│   ├── schemas/                      # DB schema definitions
│   │   ├── init-db.sql               # Generated from SQL source; run on Postgres startup
│   │   └── *.sql                     # Schema files
│   ├── models/                       # Python data models
│   ├── local_dataset/                # Local dataset builder
│   ├── news/                         # News/updates module
│   └── suggestions/                  # Suggestion system
│
├── docker/                           # Docker configuration
│   ├── docker-compose.yml            # Postgres + Redis services
│   ├── app.compose.override.yml      # Backend + frontend services (dev)
│   ├── Dockerfile.cron               # Ranking cron job service (separate Railway)
│   ├── Dockerfile.backend            # Backend service
│   ├── Dockerfile.frontend           # Frontend service (if needed)
│   └── data/
│       ├── init-db.sql               # DB initialization script
│       └── ...
│
├── scripts/                          # Utility scripts
│   ├── generate_mcp_registry.py      # Auto-generate mcp_servers.json from mcp_servers/*/ sources
│   ├── auth_setup.py                 # Browser-based OAuth flow (Phase 3 admin endpoint alternative)
│   ├── synthetic_monitor.py          # Synthetic monitoring (health checks)
│   ├── fixtures/                     # Test fixture data
│   └── ...
│
├── docs/                             # Documentation
│   ├── adr/                          # Architecture Decision Records
│   │   ├── 0001-oauth-rekey-via-admin-endpoint.md
│   │   └── ...
│   └── ...
│
├── .planning/                        # GSD planning (auto-managed)
│   └── codebase/                     # Codebase docs (this file, ARCHITECTURE.md)
│
├── backend/mcp_servers.json          # Generated MCP server registry (auto-updated by generate_mcp_registry.py)
├── pyproject.toml                    # uv workspace manifest (Python)
├── package.json                      # Root package (typically empty, frontend has its own)
├── Makefile                          # Task automation (dev, docker, deploy, test)
├── railway.toml                      # Railway deployment config (backend/frontend/cron services)
└── CLAUDE.md                         # Per-project Claude instructions
```

## Directory Purposes

**`backend/`** — FastAPI server (Python 3.13, async, uvicorn):
- Receives HTTP requests from frontend
- Coordinates session state (Redis), persistence (Postgres), MCP calls, LLM calls
- Three routers: arena (LLM duel), tool_arena (MCP duel), llms (model metadata)
- Self-contained modules per router to minimize cross-imports

**`frontend/`** — SvelteKit static site (Node.js, Vercel):
- Single-page app served pre-rendered or on-demand
- Calls backend API endpoints
- Renders blind comparison UI, vote panel, reveal screen
- i18n support (5 languages via Paraglide)
- DSFR design system (French government accessibility standards)

**`mcp_servers/`** — MCP server implementations (Docker, Railway):
- rag_pill: Registry pattern (pill YAML + engine adapter) supports multiple frameworks
- langchain_rag, llamaindex_rag: Single-pipeline variants (simpler, less flexible)
- All deployed as separate Railway services with independent scaling
- Called by dispatcher via streamable HTTP (not stdio)

**`utils/`** — Shared utilities (loosely-coupled workflows):
- ranking: Cron job (separate Railway service) rebuilds leaderboard hourly
- storage: DB and Redis clients used by backend
- schemas: DB migrations and definitions

**`docker/`** — Docker Compose setup (dev/test):
- Postgres 16, Redis services
- Optional: backend, frontend containers for full-stack Docker testing

**`scripts/`** — One-off utilities:
- generate_mcp_registry.py: Reads all mcp_servers/*/config, writes backend/mcp_servers.json
- auth_setup.py: OAuth browser flow (for admin re-keying)
- synthetic_monitor.py: Health check script

**`docs/`** — Design documentation:
- ADRs for major decisions (OAuth re-key, blind comparison guarantees)
- Runbooks for operations

## Key File Locations

**Entry Points:**

- `backend/main.py`: FastAPI app initialization (routers, middleware, lifespan)
- `mcp_servers/rag_pill/server.py`: RAG Pill MCP server (FastMCP)
- `mcp_servers/langchain_rag/main.py`: LangChain MCP server
- `mcp_servers/llamaindex_rag/main.py`: LlamaIndex MCP server
- `frontend/src/routes/+layout.svelte`: SvelteKit root layout
- `frontend/src/routes/tool-arena/+page.svelte`: MCP arena main page

**Configuration:**

- `backend/config.py`: Global settings (CountryPortal, OBJECTIVES, SelectionMode)
- `backend/tool_arena/config.py`: MCPServerConfig, load_mcp_servers (MCP-specific, no arena imports)
- `backend/mcp_servers.json`: Auto-generated registry of MCP servers (read by load_mcp_servers)
- `pyproject.toml`: Python workspace (uv)
- `railway.toml`: Railway deployment (backend, frontend, cron services)

**Core Logic (Tool Arena):**

- `backend/tool_arena/dispatcher.py`: Orchestrate two concurrent MCP calls, normalize, sanitize
- `backend/tool_arena/client.py`: Single MCP call wrapper (credential dispatch, tool discovery)
- `backend/tool_arena/normalizer.py`: Convert raw output to NormalizedEnvelope
- `backend/tool_arena/sanitizer.py`: Redact server identities from text and URLs
- `backend/tool_arena/credential.py`: Auth type dispatch (none, api_key, bearer, oauth2)
- `backend/tool_arena/registry.py`: Load MCP servers, support server selection
- `backend/tool_arena/readiness.py`: Track per-server health, background probing

**Data Persistence (Tool Arena):**

- `backend/tool_arena/models.py`: MCPToolCall, ToolCallRecord (Pydantic)
- `backend/tool_arena/persistence.py`: save_tool_call_to_db, save_tool_vote_to_db
- `backend/tool_arena/session.py`: Redis session store for blind state
- `utils/storage/db.py`: Postgres client and schema
- `utils/storage/redis.py`: Redis client and key constants

**Testing:**

- `backend/tool_arena/tests/`: Unit tests (normalizer, sanitizer, credential, readiness, dispatcher, client)
- `mcp_servers/rag_pill/tests/`: rag_pill tests (engine selection, pill loading, retry logic)
- `frontend/e2e/`: Playwright end-to-end tests (demo.test.ts, modeles.test.ts)

## Naming Conventions

**Files:**

- Python modules: `snake_case.py` (e.g., `dispatcher.py`, `normalizer.py`)
- MCP server entry points: `server.py` or `main.py`
- SvelteKit pages: `+page.svelte`, `+layout.svelte`
- Components: `PascalCase.svelte` (e.g., `CompareCard.svelte`)
- Test files: `test_*.py` (Python), `*.test.ts` (SvelteKit)

**Directories:**

- Python packages: `snake_case/` (e.g., `tool_arena/`, `mcp_servers/`)
- Feature modules: `snake_case/` (e.g., `arena/`, `rag_pill/`)
- SvelteKit routes: `kebab-case/` (e.g., `tool-arena/`, `leaderboard/`)

**Functions & Classes:**

- Python: `snake_case()` functions, `PascalCase` classes (per PEP 8)
- TypeScript/SvelteKit: `camelCase()` functions, `PascalCase` components
- Constants: `UPPER_SNAKE_CASE` (Python), `UPPER_CASE` (TypeScript)

**Configuration:**

- JSON files: `snake_case.json` (e.g., `mcp_servers.json`)
- Environment variables: `UPPER_SNAKE_CASE` (e.g., `OPENROUTER_API_KEY`, `MCP_CALL_TIMEOUT`)
- YAML files: `snake_case.yaml` (e.g., `default_summary.yaml` in rag_pill/pills/)

## Where to Add New Code

**New MCP Server:**
1. Create `mcp_servers/{name}/` with `server.py` (FastMCP), `requirements.txt`, optional `Dockerfile`
2. Add config entry to `backend/mcp_servers.json` (or regenerate via `scripts/generate_mcp_registry.py`)
3. Registry auto-loads on backend startup

**New MCP Tool (within existing server):**
- rag_pill: Create `engines/{engine_name}.py` inheriting `RAGEngine`, update `server.py` engine list
- langchain_rag / llamaindex_rag: Extend `main.py` with new `@mcp.tool()`

**New Backend Route:**
1. Add handler to appropriate router: `backend/arena/router.py`, `backend/tool_arena/router.py`, or new router
2. Add Pydantic models to `backend/arena/models.py` or `backend/tool_arena/models.py`
3. Persistence: Add method to `backend/{module}/persistence.py` if DB write needed
4. Include router in `backend/main.py` via `app.include_router()`

**New Frontend Page:**
1. Create `frontend/src/routes/{feature}/+page.svelte`
2. Add API client helpers in `frontend/src/lib/api/{feature}.ts` if needed
3. Import DSFR components from `frontend/src/lib/components/dsfr/`
4. Add i18n keys to `frontend/locales/*.json`

**New Utility (DB, Redis, etc.):**
- Place in `utils/{purpose}/` with clear module structure
- If used by backend: import from `backend.utils.storage.db` or `backend.utils.storage.redis` (shared)
- If standalone cron job: separate Poetry env in `utils/ranking_methods/`

**New Test:**
- Backend: `backend/tool_arena/tests/test_*.py` (pytest, async-capable)
- MCP servers: `mcp_servers/rag_pill/tests/` (pytest)
- Frontend: `frontend/e2e/*.test.ts` (Playwright)

## Special Directories

**`backend/tool_arena/migrations/`** — DB schema updates:
- Migration files numbered by date/sequence
- Used by deployment scripts to update Postgres schema

**`mcp_servers/rag_pill/pills/`** — RAG configuration library:
- YAML files defining pill configs (embedder, strategy, framework hints)
- Loaded by PillRegistry at startup
- Not versioned per-server; loaded fresh on each MCP server restart

**`mcp_servers/rag_pill/engines/`** — Framework adapters:
- One file per RAG framework (LangChain, LlamaIndex, Haystack, etc.)
- Each inherits RAGEngine, implements SUPPORTS (task types) and run() method
- Failures logged with engine_id and error reason
- Not disabled at module import; if framework not installed, SUPPORTS=[] and warnings logged at server startup

**`frontend/locales/`** — i18n translations:
- One `.json` per language (fr.json, da.json, sv.json, et.json, lt.json)
- Keys match TypeScript i18n schema
- Updated by translators or automated tools

**`.planning/codebase/`** — GSD documentation (auto-managed):
- ARCHITECTURE.md (this analysis)
- STRUCTURE.md (this file)
- CONVENTIONS.md (coding style)
- TESTING.md (test patterns)
- CONCERNS.md (technical debt)
- Written by `/gsd:map-codebase` orchestrator tool
