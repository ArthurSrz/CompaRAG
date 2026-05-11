# External Integrations

**Analysis Date:** 2026-05-11

## APIs & External Services

**LLM Provider:**
- OpenRouter (`openrouter.ai/api/v1`)
  - SDK: litellm ==1.77.5
  - Auth: `OPENROUTER_API_KEY` env var
  - Used by: `backend/arena/` for model inference, all RAG engines for generation
  - Models: Mistral (small/medium), customizable via `backend/config.py`

**RAG Platform (External MCP Server):**
- Clarifeye (`https://env-3256.gcp.clarifeye.io/mcp`)
  - SDK: MCP SDK (Python `mcp>=1.9.0,<2`)
  - Auth: OAuth2 code flow with refresh token rotation
  - Tool: `call_agent` (agentic synthesis via Clarifeye's internal LLM)
  - Token storage: Redis (production) or `.oauth_tokens/` (local dev)
  - Env vars: `CLARIFEYE_CLIENT_SECRET`, tokens in Redis key `oauth_tokens:clarifeye`
  - Config file: `mcp_servers.external.json` (project_id, agent_settings_id)

**Embedding Providers (rag_pill engines):**
- OpenRouter (default)
  - Endpoint: `https://openrouter.ai/v1`
  - API key: `OPENROUTER_API_KEY`
  - Fallback: `EMBEDDING_API_KEY` → `OPENAI_API_KEY` → `OPENROUTER_API_KEY`
- OpenAI (optional override)
  - Endpoint: `EMBEDDING_BASE_URL` env var
  - API key: `EMBEDDING_API_KEY`
- Hugging Face (local embeddings)
  - Model: sentence-transformers (bundled)

**Google Cloud:**
- Vertex AI (optional)
  - Auth: `GOOGLE_APPLICATION_CREDENTIALS` (JSON key file path)
  - Client: `google-cloud-aiplatform>=1.75.0`
  - Env vars: `GOOGLE_APPLICATION_CREDENTIALS`, `VERTEXAI_LOCATION`

**Other Models (Optional):**
- Albert API: `ALBERT_KEY` env var (purpose: unclear, potentially deprecated)
- Hugging Face Inference: `HF_INFERENCE_KEY` env var
- OrdBogen API: `ORDBOGEN_API_KEY` env var

## Data Storage

**Databases:**
- PostgreSQL 16 (primary)
  - Connection: `COMPARIA_DB_URI` env var (format: `postgresql://user:pass@host:port/db`)
  - Client: psycopg2-binary (synchronous, no async ORM)
  - Schemas: `utils/schemas/` (SQL source of truth)
  - Migrations: `backend/tool_arena/migrations/`
  - Structured logging target: `backend/logger.py` (PostgresHandler)
  - Data tables: conversations, votes, reactions, logs (per schema files)

**Cache Store:**
- Redis (in-memory cache)
  - Connection: `COMPARIA_REDIS_HOST` (default: localhost), port 6379
  - Password: `COMPARIA_REDIS_PASSWORD` env var (optional)
  - Client: redis[hiredis] >=7.1.0 (synchronous with C extension)
  - Init: `utils/storage/redis.py` singleton with lru_cache
  - Keys (patterns):
    - `session:{session_hash}` - Arena conversation state
    - `ip:{ip}` - User character count rate limiting
    - `{country_code}_count` - Vote counts per country
    - `rankings_and_prefs:{country_portal}` - Cached leaderboard data
    - `llm_cache:{model_name}:{prompt_hash}` - Response caching (if `CACHE_ENABLED=true`)
    - `tool_arena:ranking` - Tool ranking leaderboard
    - `oauth_tokens:{server_id}` - OAuth2 token storage (Clarifeye, etc.)
    - `oauth_client_info:{server_id}` - OAuth2 client metadata

**File Storage:**
- Local filesystem (development)
  - OAuth tokens: `.oauth_tokens/` directory (FileTokenStorage fallback)
  - Logs: `data/` directory (configured via `settings.LOGDIR`)
  - Document index: `documents_index.json`
  - Documents: `documents/` directory (paired with index)
- S3-compatible (OVH, production)
  - Env vars: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL`, `AWS_DEFAULT_REGION`
  - Purpose: document uploads, backup, dataset export

## Authentication & Identity

**OAuth2 (MCP Servers):**
- Type: Authorization code flow with PKCE (S256)
- Framework: MCP SDK's `OAuthClientProvider`
- Token refresh: Automatic via refresh_token; distributed lock via Redis (`oauth_refresh_lock:{server_id}`)
- Token storage:
  - Production: RedisTokenStorage (survives Railway redeploys)
  - Local dev: FileTokenStorage (writes to `.oauth_tokens/` on disk)
- Seeding: Manual OAuth flow via `scripts/auth_setup.py` → `POST /admin/tool-arena/oauth/seed`
- Servers using OAuth2:
  - Clarifeye: `client_id=Zlq2o82F4VDm7CV-vue4l8h-nSHgoj-B8lt0_XM7chc`, token_url at env-3256.gcp.clarifeye.io

**API Key Authentication:**
- Bearer token auth for admin endpoints
  - `ADMIN_STATUS_TOKEN` env var
  - Required for `POST /admin/tool-arena/oauth/seed`, `GET /admin/tool-arena/status`
  - Returns 401 if missing or unset (endpoint considered "not available")

**Session Management:**
- Session-based for arena/tool-arena (not token-based)
- Session hash stored in Redis
- IP-based rate limiting: character counts stored per IP in Redis

## MCP Servers Registry

**Local MCP Servers:**
- Entry point: `mcp_servers/start_servers.sh`
- Registry file: `backend/mcp_servers.json` (auto-generated via `make mcp-registry`)
- Server types:
  1. **rag_pill** (multi-engine registry):
     - Endpoint: `http://localhost:8012/mcp`
     - Instances per (pill_id, engine_id) pair: langchain, llamaindex, haystack, txtai (chroma dependencies bundled)
     - Tool: `rag_pill_query`
     - Railway deploy: Manual (not auto-deployed with git push) — use `railway up --service rag-pill`
  2. **langchain_rag** (single pipeline):
     - Endpoint: `http://localhost:8013/mcp` (assumed)
     - Tool: `rag_query` or similar
     - LLM: configurable via `LANGCHAIN_RAG_LLM_ID` env var
  3. **llamaindex_rag** (single pipeline):
     - Endpoint: `http://localhost:8014/mcp` (assumed)
     - Tool: `rag_query` or similar
     - LLM: configurable via `LLAMAINDEX_RAG_LLM_ID` env var

**External MCP Servers:**
- Registry file: `mcp_servers.external.json`
- Clarifeye: endpoint `https://env-3256.gcp.clarifeye.io/mcp`

**MCP Transport:**
- Transport: `streamablehttp` (HTTP POST with SSE for bidirectional communication)
- Timeout: `MCP_CALL_TIMEOUT` env var (default 90s), overridable per-server via `timeout_seconds`
- Client: `backend/tool_arena/client.py` → `single_mcp_call()` function
- Authentication: OAuth2 (Clarifeye) or bearer/API-key headers per `backend/tool_arena/credential.py`

## Monitoring & Observability

**Error Tracking:**
- Sentry
  - DSN: `SENTRY_DSN` env var
  - Environment: `SENTRY_ENVIRONMENT` env var (default: dev)
  - Sample rate: `SENTRY_SAMPLE_RATE` (default 0.2)
  - Initialization: `backend/sentry.py`

**Logging:**
- Structured JSON logging (default) or RAW (set `LOG_FORMAT=RAW` for local dev)
- Handlers:
  - PostgreSQL (via `backend/logger.py`): structured logs appended to Postgres table
  - Console (uvicorn)
  - Loki (optional): `python-logging-loki>=0.3.1` (configured but not mandatory)
- Frontend logging: Winston ^3.17.0 with Loki plugin (`winston-loki` ^6.1.2)

**Metrics & Monitoring:**
- Prometheus metrics: `prometheus-fastapi-instrumentator>=7.0.0`
- Endpoint: `/metrics` (exposes FastAPI instrumentation)
- Frontend metrics: `prom-client` ^15.1.3

**Readiness Probe:**
- Background loop: `backend/tool_arena/readiness.py`
- Probes MCP servers every `get_probe_interval_seconds()` to detect Ready/Unavailable states
- Initial budget: 30 seconds; individual probes: 10 seconds each
- Used by dispatcher to filter out unhealthy servers before selection

## CI/CD & Deployment

**Container Registry:**
- Harbor (OVH)
  - Registry: `55h10w99.gra7.container-registry.ovh.net`
  - Project: `atnum` (default)
  - Credentials: `HARBOR_USERNAME`, `HARBOR_PASSWORD` env vars
  - Images:
    - `languia:${GIT_COMMIT}` / `languia:${BRANCH_NAME}` (backend)
    - `languia-front:${GIT_COMMIT}` / `languia-front:${BRANCH_NAME}` (frontend)

**Frontend Deployment:**
- Vercel
  - Framework: SvelteKit with `@sveltejs/adapter-vercel`
  - Build: `npm run build` (pre-configured in `frontend/package.json`)
  - Auto-deploy from git: Yes (on develop/main branch)

**Backend Deployment:**
- Railway
  - Service 1 (backend + frontend): Auto-deploy from git push
  - Service 2 (rag-pill MCP): Manual deploy — `railway up --service rag-pill`
  - Service 3 (cron ranking): Separate service via `railway.cron.toml` (hourly schedule: `0 * * * *`)
  - Port: `PORT` env var (default 80 in Docker)
  - Health check: Readiness probe at `/admin/tool-arena/status` (requires `ADMIN_STATUS_TOKEN`)

**Infrastructure as Code:**
- Docker Compose: `docker/docker-compose.yml` + `docker/app.compose.override.yml`
  - Services: postgres:16, redis, backend, frontend
  - Volumes: db-data, pglogs
  - Network: internal Docker network
- Build config: `docker/docker-bake.yml` (multi-stage, buildx optimization)

## Environment Configuration

**Required env vars (production):**
- `COMPARIA_DB_URI` - PostgreSQL connection string
- `COMPARIA_REDIS_HOST` - Redis hostname
- `OPENROUTER_API_KEY` - LLM provider API key
- `CLARIFEYE_CLIENT_SECRET` - OAuth2 client secret for Clarifeye
- `ADMIN_STATUS_TOKEN` - Admin API token for readiness/rekey endpoints
- `MCP_CALL_TIMEOUT` - MCP server timeout in seconds (default 90)
- `SENTRY_DSN` - Sentry error tracking DSN
- `GIT_COMMIT` - Git commit hash (injected at build time)

**Optional env vars:**
- `GOOGLE_APPLICATION_CREDENTIALS` - GCP service account JSON key path
- `VERTEXAI_LOCATION` - GCP Vertex AI location
- `HF_INFERENCE_KEY` - Hugging Face API key
- `ALBERT_KEY` - Albert API key (deprecated?)
- `ORDBOGEN_API_KEY` - OrdBogen dictionary API
- `HF_PUSH_DATASET_KEY` - Hugging Face token for dataset export
- `CACHE_ENABLED` - Enable response caching (default false)
- `CACHE_PROBABILITY` - Cache hit serving probability (0.0-1.0)
- `CACHE_TTL` - Cache lifetime in seconds (default 172800 = 48h)
- `CACHE_MAX_RESPONSES` - Max cached responses per (model, prompt) pair
- `LANGUIA_DEBUG` - Debug mode (default false)
- `LOG_FORMAT` - JSON or RAW (default JSON for production, RAW for dev)
- `SENTRY_SAMPLE_RATE` - Sentry sampling (0.0-1.0)
- `COMPARIA_REDIS_PASSWORD` - Redis password (optional)
- `LANGCHAIN_RAG_LLM_ID` - Override LLM for langchain_rag engine
- `LLAMAINDEX_RAG_LLM_ID` - Override LLM for llamaindex_rag engine
- `EMBEDDING_BASE_URL` - Embedding API endpoint (overrides default OpenRouter)
- `EMBEDDING_API_KEY` - Embedding API key (if different from LLM key)
- `RAG_PILL_EMBEDDING_RETRIES` - Retry count for embedding failures (default 2)
- `COMPARAG_SYNTHETIC_DISABLED` - Disable synthetic monitor (set to 1)
- `OAUTH_PREWARM_TIMEOUT` - OAuth pre-warm handshake timeout (default 20s)

**Secrets location:**
- Production: Railway environment variables dashboard
- Local dev: `.env` file (ignored by git via `.gitignore`)
- OAuth tokens (production): Redis key-value store
- OAuth tokens (local dev): `.oauth_tokens/` directory (JSON files)

## Webhooks & Callbacks

**Incoming:**
- None detected (arena/tool-arena are pull-based, no webhooks)

**Outgoing:**
- Dataset export: `utils/export_dataset.py` pushes to Hugging Face Hub (`huggingface_hub>=1.4`)
- Logs: Structured logs sent to Sentry (via SDK)
- Optional: Logs sent to Grafana Loki (via `python-logging-loki`)

---

*Integration audit: 2026-05-11*
