# Coding Conventions

**Analysis Date:** 2026-05-11

## Language & Tools

**Python (Backend):**
- Python 3.13+ (`pyproject.toml` line 6)
- Formatter: black
- Import sorter: isort (profile: black)
- Linter: mypy (check_untyped_defs: true)
- Cleanup: autoflake (remove-all-unused-imports: true)
- Run via `make lint-python` and `make format-python`

**TypeScript/JavaScript (Frontend):**
- TypeScript 5.9+ with strict config
- Formatter: Prettier (3.8.1+)
- Linter: ESLint 9 with TypeScript support
- Svelte support: eslint-plugin-svelte, prettier-plugin-svelte
- Run via `cd frontend && npm run lint` / `npm run format:fix`

## Naming Patterns

**Python Files (backend/):**
- Modules: `snake_case` (e.g., `credential.py`, `normalizer.py`, `embedding_validator.py`)
- Classes: `PascalCase` (e.g., `NormalizedEnvelope`, `Source`, `ApiKeyAuth`, `CredentialRevoked`)
- Functions: `snake_case` (e.g., `normalize_output`, `validate_document_embeddings`)
- Private functions: Prefix with `_` (e.g., `_parse_sources`, `_require`)
- Constants: `SCREAMING_SNAKE_CASE` (e.g., `EMBEDDING_EMPTY_DATA_MARKER`)
- Protocol/Type aliases: `PascalCase` (e.g., `MCPAuthConfig`)

**Frontend Routes (SvelteKit):**
- Kebab-case directories and files (e.g., `tool-arena/`, `+layout.svelte`)
- Page routes: `+page.svelte`
- Server routes: `+page.server.ts` (SvelteKit server functions)
- Layout files: `+layout.svelte`, `+layout.ts`
- Error pages: `+error.svelte`

**Svelte Components (src/lib/components/):**
- PascalCase filenames (e.g., `ModelCard.svelte`, `IconButton.svelte`, `ThemeSelector.svelte`)
- Follow one component per file

**TypeScript Files:**
- Modules/files: kebab-case (e.g., `demo.test.ts`)
- Classes: `PascalCase`
- Functions: `camelCase`
- Types/Interfaces: `PascalCase`

## Code Style

**Formatting:**
- Python: Black (4-space indents implicit via black default)
- Frontend: Prettier with single quotes (`singleQuote: true`), trailing comma disabled (`trailingComma: "none"`), 100 char line width, no semicolons (`semi: false`)

**Imports:**
Python:
```python
# isort (black profile) — three groups:
# 1. Standard library
from pathlib import Path
import json
import os

# 2. Third-party
from pydantic import BaseModel
from fastapi import FastAPI

# 3. Local (relative imports)
from backend.tool_arena.config import MCPServerConfig
```

TypeScript/Svelte:
```typescript
// ESLint standard order (enforced by eslint:recommended):
// 1. Browser globals
// 2. Node globals
// 3. External packages
import { expect, test } from '@playwright/test'
import { describe, it } from 'vitest'

// 4. Absolute imports (aliases in svelte.config.js)
import { $css: './src/css' } from '$css'
import { $components: './src/lib/components' } from '$components'

// 5. Relative imports
import Component from './Component.svelte'
```

**Path Aliases (svelte.config.js):**
- `$css` → `./src/css`
- `$components` → `./src/lib/components`

## Error Handling

**Python Strategy:**
- Typed exception hierarchy (domain-specific base classes)
- Raises before returns (fail-fast)
- No generic `Exception` — use specific types

**Pattern Example (credential.py):**
```python
class CredentialError(Exception):
    """Base class for credential acquisition failures."""

class CredentialRevoked(CredentialError):
    """Refresh token rejected / interactive OAuth flow required."""

class CredentialMisconfigured(CredentialError):
    """Configuration error: missing env var, malformed config, etc."""

class CredentialUpstreamDown(CredentialError):
    """Token endpoint unreachable or returning 5xx / timeouts."""
```

Callers catch specific types:
```python
try:
    await cred.headers_for(server)
except CredentialMisconfigured:
    # Config inputs missing
    ...
except CredentialRevoked:
    # OAuth tokens unrecoverably rejected — trigger reauth flow
    ...
except CredentialUpstreamDown:
    # Token endpoint unreachable — retry or circuit-break
    ...
```

**Retry Markers (rag_pill):**
Use `ValueError` with sentinel message string to signal retryable failures:
```python
# embedding_validator.py — converts None embeddings to retryable error
EMBEDDING_EMPTY_DATA_MARKER = "No embedding data received"

def _require(value: Any) -> Any:
    if value is None:
        raise ValueError(EMBEDDING_EMPTY_DATA_MARKER)
    return value

def validate_document_embeddings(result: Any) -> dict:
    # Raises ValueError(EMBEDDING_EMPTY_DATA_MARKER) on None embedding
    # → existing retry.execute_with_embedding_retry wrapper picks it up
    for doc in _require(payload.get("documents")):
        _require(getattr(doc, "embedding", None))
    return result
```

This pattern allows downstream retry machinery to:
1. Check for `ValueError` without catching all value errors
2. Match the specific sentinel message string
3. Retry without modifying the boundary validator or retry logic

**Frontend Error Handling:**
- ESLint warns on unhandled Promise rejections
- TypeScript strict mode enforces return types on async functions
- Use try/catch in `+page.server.ts` handlers

## Logging

**Backend (logger = logging.getLogger("languia")):**
- Structured logging via `logging` module
- Log level: INFO for events, DEBUG for detailed traces
- No print() statements in production code — use logger.info()

**Frontend:**
- Winston + Winston-Loki (per `frontend/package.json`)
- Built-in browser console for development
- No console.log in production components — use structured logger

## Comments & Documentation

**When to Comment:**
- Why, not what (code should be clear about what)
- Module-level docstrings for all files: explain purpose and key design decisions
- Class docstrings for public classes (Pydantic models, Protocols, etc.)
- Function docstrings for public functions (use triple quotes)

**Docstring Style (Python):**
- Pydantic model: `"""Short description. Longer explanation if needed."""`
- Function with complex logic: Args/Returns/Raises sections
- Protocol or interface: Document the contract, not implementation

**Example (credential.py):**
```python
"""Credential Module — single dispatch seam for MCP server auth.

Phase 1 of the OAuth refactor: collapse per-call auth-type branching in
``client.py`` into a small Adapter family behind a uniform ``Credential``
Protocol...

Known asymmetry — OAuth and the MCP SDK
---------------------------------------
[Detailed explanation of design decision]
"""

@runtime_checkable
class Credential(Protocol):
    """Uniform interface for obtaining MCP request auth headers.
    
    Implementations must be cheap to call repeatedly — the per-server cache
    in ``credential_for`` ensures only one instance exists per server id.
    """
    
    async def headers_for(self, server: MCPServerConfig) -> dict[str, str]:
        """Return HTTP headers to attach to the MCP request.
        
        For OAuth servers the SDK's ``auth=provider`` integration is the
        authoritative path — see module docstring. ...
        
        Raises:
            CredentialMisconfigured: Config inputs missing.
            CredentialRevoked: OAuth tokens unrecoverably rejected.
            CredentialUpstreamDown: Token endpoint unreachable.
        """
        ...
```

## Configuration Management

**Backend (backend/config.py):**
- Centralized `Settings` class using Pydantic BaseSettings
- Loads from environment variables + optional `.env` file
- Never hardcode secrets — reference env var names

**Per-Module Config (backend/tool_arena/config.py):**
- Self-contained module — does NOT import from `backend.arena` or `backend.config`
- Allows loading in tests without pulling in psycopg2/Redis
- Example: `MCPServerConfig` is defined here, not in root config

**Auth Config Pattern (backend/tool_arena/config.py):**
Use Pydantic discriminated unions for polymorphic auth:
```python
class OAuth2Auth(BaseModel):
    type: Literal["oauth2"]
    client_id: str
    client_secret_env: str  # env var name, never literal

class ApiKeyAuth(BaseModel):
    type: Literal["api_key"]
    key_env: str  # env var name
    header: str = "Authorization"

class BearerAuth(BaseModel):
    type: Literal["bearer"]
    token_env: str  # env var name

class NoAuth(BaseModel):
    type: Literal["none"]

MCPAuthConfig = Annotated[
    OAuth2Auth | ApiKeyAuth | BearerAuth | NoAuth,
    Field(discriminator="type"),
]
```

Loading: `MCPServerConfig.model_validate(raw_dict)` — Pydantic routes to correct auth type.

## Internationalization (i18n)

**Framework:** Paraglide.js (`@inlang/paraglide-js`)

**File Structure (frontend/src/lib/i18n/):**
- `messages.js` — message loader
- `registry.js` — language registry
- `runtime.js` — translation runtime
- `server.js` — server-side helpers
- `messages/` — language message files (generated)

**Usage Pattern:**
```svelte
<script>
  import * as m from '$lib/i18n/runtime'
</script>

<h1>{m.page_title()}</h1>
<p>{m.greeting({ name: 'Alice' })}</p>
```

**Supported Locales:** `fr`, `da`, `sv`, `et`, `lt` (see `frontend/package.json` dependencies)

## Special Conventions

**Pydantic Models:**
- Always include field docstrings for public fields
- Use `|` union syntax (Python 3.10+) instead of `Union[A, B]`
- Use `field.model_validate(dict)` for loading, not constructor
- Include example in docstring if the model is used in public APIs

**Protocol/Interface (Python):**
- Prefix with `@runtime_checkable` decorator
- Used for structural typing — allow any object satisfying methods
- Document the contract in module docstring

**Async Functions:**
- Prefix `async def` for async functions
- Use `pytest-anyio` for async test fixtures
- Await all async calls — no fire-and-forget

## Module Organization

**Backend (backend/tool_arena/):**
- `config.py` — Pydantic models for MCP server configuration (self-contained, no cross-imports)
- `credential.py` — Auth credential dispatch (Adapters, Protocol, typed errors)
- `normalizer.py` — Output envelope normalization pipeline
- `sanitizer.py` — Sensitive data redaction
- `router.py` — FastAPI endpoints
- `client.py` — MCP server calls
- `dispatcher.py` — Two-server selection logic
- `tests/` — Pytest test files (mirroring module structure)

**Frontend (frontend/src/):**
- `routes/` — SvelteKit pages (kebab-case directories)
- `lib/components/` — Reusable Svelte components (PascalCase)
- `lib/i18n/` — Paraglide.js translations (generated)
- `css/` — Tailwind + global styles

---

*Convention analysis: 2026-05-11*
