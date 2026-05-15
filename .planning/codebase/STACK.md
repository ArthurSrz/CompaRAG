# Technology Stack

**Analysis Date:** 2026-05-11

## Languages

**Primary:**
- Python 3.13 - Backend (FastAPI), MCP servers, utilities, ranking pipeline
- TypeScript 5.9.3 - Frontend (SvelteKit) with strict type checking
- JavaScript - Frontend build tooling and dependencies

**Secondary:**
- SQL (PostgreSQL) - Database schema and migrations
- YAML - Docker Compose, Railway configuration
- JSON - Configuration, ontology, MCP server registry

## Runtime

**Environment:**
- Python 3.13 (Docker base: `python:3.13-slim`)
- Node.js (via `@sveltejs/adapter-vercel` and SvelteKit)
- Browser runtime (SvelteKit client-side code)

**Package Manager:**
- `uv` (0.7.2 minimum, via Dockerfile) - Python dependency management and lockfile (`uv.lock`)
- `yarn` - Frontend npm package management (fallback: `npm install --legacy-peer-deps`)
- Poetry - Separate Poetry env for ranking methods in `utils/ranking_methods/`

## Frameworks

**Core Backend:**
- FastAPI >=0.128.0 - HTTP/REST API framework with async/await
  - Entry point: `backend/main.py`
  - CORS middleware configured via `backend/cors_utils.py`
  - Prometheus instrumentation: `prometheus-fastapi-instrumentator>=7.0.0`

**Frontend:**
- SvelteKit ^2.53.0 - Full-stack framework (SSR + client)
  - Adapter: `@sveltejs/adapter-vercel` ^6.3.3 for Vercel deployment
  - Build tool: Vite ^7.3.1
  - Router: SvelteKit file-based routing under `frontend/src/routes/`

**MCP/RAG Servers:**
- FastMCP >=2.0.0 - MCP server framework used by all three RAG engines
  - `mcp_servers/_legacy_standalone_servers/langchain_rag/` - LangChain-based pipeline
  - `mcp_servers/_legacy_standalone_servers/llamaindex_rag/` - LlamaIndex-based pipeline
  - `mcp_servers/rag_pill/` - Multi-engine registry with pluggable strategies

**Testing & Development:**
- pytest >=9.0.2 - Backend unit/integration tests
- pytest-anyio - Async test support
- Playwright ^1.58.2 - End-to-end frontend testing
- vitest ^4.0.18 - Unit tests for frontend code
- svelte-check ^4.4.3 - Svelte type checking

**Code Quality:**
- mypy >=1.19.1 - Python type checking (excludes `utils/ranking_methods`)
- ESLint ^9.39.2 - JavaScript/TypeScript linting
- Prettier ^3.8.1 - Code formatting (Python: black, isort, autoflake)
- black >=26.1.0 - Python code formatter
- isort >=7.0.0 - Import sorting
- autoflake >=2.3.1 - Unused import removal

## Key Dependencies

**Critical Backend:**
- `litellm==1.77.5` - LLM provider abstraction layer (OpenRouter, Google Vertex AI, OpenAI)
  - Used by `backend/arena/` for model selection and streaming
  - Uses `litellm.acompletion` for concurrent model calls
  - Token counter: `litellm.litellm_core_utils.token_counter`
- `mcp>=1.9.0,<2` - MCP SDK for client-side tool calls and OAuth2 handling
  - `mcp.ClientSession` for streamablehttp connections
  - `mcp.client.auth.OAuthClientProvider` for OAuth2 token management
  - `mcp.client.streamable_http.streamablehttp_client` for MCP HTTP transport

**Database & Caching:**
- `psycopg2-binary>=2.9.11` - PostgreSQL driver (synchronous)
  - Used in `backend/logger.py` for structured logging to Postgres
  - Used in `backend/tool_arena/models.py` for session/vote persistence
  - No async ORM; direct SQL execution via `psycopg2.sql`
- `redis[hiredis]>=7.1.0` - Redis client with hiredis C extension for performance
  - Connection: `utils/storage/redis.py` singleton
  - Used for response caching, session state, ranking data, OAuth token storage
  - Keys: conversations, user character counts, rankings, LLM responses, tool rankings

**Serialization & Validation:**
- `pydantic>=2.12.5` - Data validation and serialization
- `pydantic-settings>=2.12.0` - Environment-based configuration (see `backend/config.py`)
- `json5>=0.13.0` - JSON5 parsing for flexible config

**RAG Engines (pluggable via `mcp_servers/rag_pill/requirements-*.txt`):**
- LangChain: `langchain>=0.3`, `langchain-community>=0.3`, `langchain-text-splitters>=0.3`, `langchain-openai>=0.2`, `faiss-cpu>=1.9`
- LlamaIndex: `llama-index-core>=0.12`, `llama-index-readers-file>=0.4`, `llama-index-embeddings-huggingface>=0.5`, `sentence-transformers>=3.0`
- Haystack: (included in `requirements-haystack.txt`, separate installation)
- txtai: (included in `requirements-txtai.txt`, separate installation)
- Chroma: (included in `requirements-chroma.txt`, via `chromadb>=0.5`)

**Document Processing:**
- `python-docx>=1.2.0` - DOCX parsing for document library
- `pypdf>=6.10.2` - PDF parsing for document library
- `markdown>=3.10.1` - Markdown parsing/rendering

**Observability:**
- `sentry-sdk>=2.50.0` - Error tracking and performance monitoring
  - Initialized in `backend/sentry.py`
- `python-logging-loki>=0.3.1` - Structured logging to Grafana Loki
- `rich>=14.2.0` - Rich terminal output for CLI tools

**HTTP & Networking:**
- `requests>=2.32.5` - Synchronous HTTP client
- `httpx>=0.28.1` - Async HTTP client (dev dependency, used in tests)

**Infrastructure & ML:**
- `google-auth>=2.38.0` - Google Cloud authentication for Vertex AI
- `google-cloud-aiplatform>=1.75.0` - Google Vertex AI client
- `numpy>=2.4.1` - Numerical operations

**Frontend UI:**
- `@gouvfr/dsfr` ^1.14.0 - French government design system components
- `d3` ^7.9.0 - Data visualization
- `mermaid` ^11.12.3 - Diagram rendering (Markdown integration)
- `prismjs` ^1.30.0 - Syntax highlighting
- `sanitize-html` ^2.17.1 - HTML sanitization
- `@inlang/paraglide-js` ^2.12.0 - i18n framework for 5 locales (fr, da, sv, et, lt)
- `marked-gfm-heading-id` ^4.1.3 - GitHub Flavored Markdown heading IDs
- `marked-highlight` ^2.2.3 - Syntax highlighting for Markdown
- Tailwind CSS ^4.2.1 - Utility-first CSS framework

**Monitoring:**
- `prom-client` ^15.1.3 - Prometheus metrics client (frontend)

## Configuration

**Environment:**
- Sourced from `.env` file at runtime via `pydantic-settings`
- See `.env.example` for full list of required/optional variables
- Critical vars: `COMPARIA_DB_URI`, `COMPARIA_REDIS_HOST`, `OPENROUTER_API_KEY`

**Backend Configuration:**
- `backend/config.py` - Main settings class with env var mapping
- `backend/tool_arena/config.py` - Tool Arena-specific config (self-contained, no imports from `backend.arena`)

**Build & Deployment:**
- `pyproject.toml` - Python dependencies and tool configuration (uv, mypy, black, isort, autoflake)
- `frontend/package.json` - Node.js dependencies and build scripts
- `Makefile` - Common tasks (install, dev, docker, tests, linting)
- `.claude/settings.json` - Claude Code MCP server config
- `vercel.json` - Vercel deployment for frontend (SvelteKit adapter)
- `railway.cron.toml` - Railway cron service for hourly ranking rebuild

## Platform Requirements

**Development:**
- Python 3.13 with uv package manager
- Node.js/Yarn for frontend
- Docker & Docker Compose for local infra (Postgres 16, Redis)
- PostgreSQL 16 client (`postgresql-client` in backend Dockerfile)

**Production:**
- Docker containerization:
  - Backend: `docker/Dockerfile` (multi-stage, Python 3.13-slim)
  - Frontend: `docker/Dockerfile.front` (Node.js build, static SPA)
  - Cron service: `docker/Dockerfile.cron` (separate ranking runner)
- Deployment platforms:
  - Frontend: Vercel (via `@sveltejs/adapter-vercel`)
  - Backend: Railway (also hosts rag-pill MCP server)
  - Cron ranking: Railway (separate service, via `railway.cron.toml`)
  - Postgres: Managed via Docker Compose (production uses external managed instance)
  - Redis: Managed via Docker Compose (production uses external managed instance)

**Network & Storage:**
- S3-compatible object storage (OVH) - Referenced in `.env.example` with AWS_* vars
- Container registry: Harbor (OVH)

---

*Stack analysis: 2026-05-11*
