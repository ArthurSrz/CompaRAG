# Testing Patterns

**Analysis Date:** 2026-05-11

## Backend Test Framework

**Test Runner:** pytest (9.0.2+)

**Async Support:** pytest-anyio (0.0.0+)
- Enables `async def test_*()` without wrapping in `asyncio.run()`
- Marker: `pytestmark = pytest.mark.anyio` at module level

**Assertion Library:** assert (pytest built-in)

**Run Commands:**
```bash
# All backend tests
uv run pytest backend/

# Single test file
uv run pytest backend/tool_arena/tests/test_normalizer.py

# Single test function
uv run pytest backend/tool_arena/tests/test_normalizer.py::test_full_envelope_passes_through

# Watch mode (requires pytest-watch plugin, not installed by default)
uv run pytest-watch backend/

# With verbose output
uv run pytest backend/ -v

# Show captured output (print statements)
uv run pytest backend/ -s

# Coverage (requires pytest-cov)
uv run pytest backend/ --cov=backend
```

**Configuration:** pyproject.toml dependencies:
- `pytest>=9.0.2`
- `pytest-anyio>=0.0.0`
- `httpx>=0.28.1` (for TestClient)

## Backend Test File Organization

**Location Strategy:** Co-located with modules in `backend/*/tests/` subdirectories

**Structure:**
```
backend/
├── tests/
│   ├── test_cors.py
│   └── test_health.py
├── tool_arena/
│   ├── config.py
│   ├── credential.py
│   ├── normalizer.py
│   ├── router.py
│   └── tests/
│       ├── test_config_overlay.py
│       ├── test_credential.py
│       ├── test_dry_run.py
│       ├── test_normalizer.py
│       ├── test_sanitizer.py
│       ├── test_auth.py
│       └── __init__.py (optional, empty)
└── arena/
    └── tests/
        └── ...
```

**Naming:**
- Test modules: `test_*.py` (module name follows what is being tested)
- Test classes: `Test*` (PascalCase) — optional, can group related tests
- Test functions: `test_*` (lowercase snake_case)

## Backend Test Structure

**Minimal Test (no app dependencies):**
```python
"""Unit tests for the output normalizer module (D-04 through D-07)."""

import json
import pytest
from backend.tool_arena.normalizer import NormalizedEnvelope, Source, normalize_output

def test_full_envelope_passes_through():
    """Test 1: normalize_output with full envelope passes through unchanged."""
    raw = json.dumps({
        "answer": "The answer is 42.",
        "sources": [{"url": "https://example.com", "title": "Example"}],
        "confidence": 0.95,
    })
    result = normalize_output(raw, duration_ms=150)
    assert result.answer == "The answer is 42."
    assert len(result.sources) == 1
```

**Test with FastAPI TestClient (isolated app):**
```python
"""Tests for POST /tool-arena/dry-run endpoint (14-02).

Uses a minimal isolated FastAPI test app to avoid psycopg2 imports.
MCP calls are mocked via unittest.mock.AsyncMock.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tool_arena.router import router

# Minimal isolated FastAPI test app (avoids psycopg2/Redis dependency)
_app = FastAPI()
_app.include_router(router)
client = TestClient(_app)

def test_dry_run_happy_path():
    """POST /tool-arena/dry-run with valid tool_id → valid=True, 3 checks."""
    raw_output = '{"answer": "This document is about testing."}'
    
    with patch("backend.tool_arena.router.registry") as mock_registry, \
         patch("backend.tool_arena.router.single_mcp_call", new_callable=AsyncMock) as mock_call:
        
        mock_registry.get_server.return_value = MagicMock(id="clarifeye")
        mock_call.return_value = (raw_output, 150)
        
        resp = client.post("/tool-arena/dry-run", json={"tool_id": "clarifeye"})
    
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
```

**Async Test with pytest-anyio:**
```python
pytestmark = pytest.mark.anyio

async def test_api_key_credential_returns_configured_header(monkeypatch):
    monkeypatch.setenv("MY_KEY_ENV", "secret-123")
    server = _server(auth=ApiKeyAuth(type="api_key", key_env="MY_KEY_ENV"))
    cred = ApiKeyCredential()
    assert await cred.headers_for(server) == {"X-Api-Key": "secret-123"}
```

**Why minimal isolated apps?**
- Full app load requires psycopg2, Redis imports → slow test startup
- Unit tests should test behavior, not infrastructure
- Use `FastAPI()` + `include_router()` to load only the code being tested
- Mock external calls (database, MCP, Redis) via `unittest.mock`

## Fixtures & Mocking

**Pattern: Fixtures for Setup/Teardown**
```python
@pytest.fixture(autouse=True)
def _reset_cache():
    """Auto-run fixture to reset credential cache before/after each test."""
    _clear_credential_cache()
    yield
    _clear_credential_cache()

def test_credential_for_caches_per_server_id():
    """Uses _reset_cache automatically."""
    server = _server("cached", auth=NoAuth(type="none"))
    first = credential_for(server)
    second = credential_for(server)
    assert first is second
```

**Pattern: Helpers for Test Data**
```python
def _server(server_id: str = "srv", auth=None) -> MCPServerConfig:
    """Return a minimal MCPServerConfig-like mock for testing."""
    return MCPServerConfig(
        id=server_id,
        name="Server",
        description="test",
        endpoint="https://example.com/mcp",
        transport="streamablehttp",
        auth=auth,
    )

def test_bearer_credential_returns_authorization_header(monkeypatch):
    monkeypatch.setenv("CLARIFEYE_API_KEY", "secret-bearer-123")
    server = _server(auth=BearerAuth(type="bearer", token_env="CLARIFEYE_API_KEY"))
    cred = BearerCredential()
    assert await cred.headers_for(server) == {"Authorization": "Bearer secret-bearer-123"}
```

**Pattern: Mocking External Calls**
```python
from unittest.mock import AsyncMock, patch

# Mock async functions
with patch("backend.tool_arena.router.single_mcp_call", new_callable=AsyncMock) as mock_call:
    mock_call.return_value = (raw_output, 150)
    # Code under test calls single_mcp_call — receives mocked result

# Mock objects
with patch("backend.tool_arena.router.registry") as mock_registry:
    mock_registry.get_server.return_value = _make_server("clarifeye")
    # Code under test calls registry.get_server() — receives mock
```

## Test Organization by Type

**Unit Tests (backend/tool_arena/tests/):**
- Focus: Single module/function behavior
- Speed: < 100ms per test
- Examples:
  - `test_normalizer.py` — JSON parsing, field defaults
  - `test_credential.py` — auth dispatch, env var loading
  - `test_sanitizer.py` — regex redaction, metadata key stripping

**Integration Tests (backend/tool_arena/tests/):**
- Focus: Component interaction (e.g., credential → MCP call)
- Speed: 100-500ms per test
- Examples:
  - `test_dry_run.py` — endpoint → credential → MCP call → response
  - `test_auth.py` — OAuth provider setup and token exchange
  - `test_dispatcher_task_type.py` — dispatcher selects correct servers

**Contract/Protocol Tests (backend/tool_arena/tests/):**
- Focus: Interface compliance (e.g., Credential Protocol)
- Speed: < 50ms per test
- Examples:
  - `test_credential.py::test_credential_protocol_runtime_check()` — all Adapters satisfy Credential

## Error Handling Tests

**Testing Typed Exceptions:**
```python
async def test_oauth2_credential_translates_runtime_error_to_revoked():
    """RuntimeError from _redirect_handler => interactive flow needed => CredentialRevoked."""
    server = _oauth_server()
    cred = OAuth2Credential()
    with patch(
        "backend.tool_arena.auth.get_oauth_provider",
        side_effect=RuntimeError("OAuth authorization_code flow triggered..."),
    ):
        with pytest.raises(CredentialRevoked):
            await cred.headers_for(server)
```

**Testing Retry Markers:**
```python
# No explicit test — retry logic tests indirectly verify ValueError marker
# See mcp_servers/rag_pill/tests/test_embedding_validator.py for examples
def test_validate_document_embeddings_raises_on_none():
    """validate_document_embeddings raises ValueError when embedding is None."""
    result = {"documents": [{"embedding": None}]}
    with pytest.raises(ValueError, match="No embedding data received"):
        validate_document_embeddings(result)
```

## Frontend Testing

**E2E Tests (frontend/e2e/):**
- Framework: Playwright (`@playwright/test` 1.58.2+)
- Config: `frontend/playwright.config.ts`
- Location: `frontend/e2e/` directory
- Naming: `*.test.ts`
- Run: `cd frontend && yarn playwright test`

**Example (frontend/e2e/demo.test.ts):**
```typescript
import { expect, test } from '@playwright/test'

test('home page has expected h1', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('h1')).toBeVisible()
})
```

**Unit Tests (frontend/src/):**
- Framework: Vitest (`vitest` 4.0.18+)
- Assertion: Vitest built-in (same as Jest)
- Location: Co-located with source (e.g., `src/demo.spec.ts`)
- Naming: `*.spec.ts`
- Run: `cd frontend && npm run test:unit` or `yarn vitest`

**Example (frontend/src/demo.spec.ts):**
```typescript
import { describe, it, expect } from 'vitest'

describe('sum test', () => {
  it('adds 1 + 2 to equal 3', () => {
    expect(1 + 2).toBe(3)
  })
})
```

**Frontend Test Commands:**
```bash
# All frontend tests (E2E + unit)
cd frontend && npm run test

# Unit tests only
cd frontend && npm run test:unit

# E2E only
cd frontend && yarn playwright test

# Watch mode (unit tests)
cd frontend && yarn vitest
```

## MCP Servers Testing

**rag_pill (mcp_servers/rag_pill/tests/):**
- Tests for embedding validators, retry logic, engine adapters
- Framework: pytest (same as backend)
- Example: `test_embedding_validator.py`

```python
def test_validate_document_embeddings_raises_on_none():
    """Validates that None embeddings trigger ValueError with retry marker."""
    from mcp_servers.rag_pill.providers.embedding_validator import validate_document_embeddings
    
    result = {"documents": [{"embedding": None}]}
    with pytest.raises(ValueError, match="No embedding data received"):
        validate_document_embeddings(result)
```

**llamaindex_rag (mcp_servers/_legacy_standalone_servers/llamaindex_rag/tests/):**
- Smoke tests for the single LlamaIndex pipeline
- Framework: pytest

**Run MCP server tests:**
```bash
# From project root
uv run pytest mcp_servers/rag_pill/tests/

# With engines group installed (for smoke tests)
uv sync --group engines
uv run pytest mcp_servers/rag_pill/tests/ -v
```

## Ranking Methods Testing (Separate Poetry Environment)

**Location:** `utils/ranking_methods/`

**Framework:** pytest (via Poetry)

**Setup:**
```bash
make ranking-install  # Installs Poetry env in utils/ranking_methods/
```

**Run:**
```bash
make ranking-test  # Runs: cd utils/ranking_methods && poetry run pytest tests/
```

**Why separate?**
- Ranking methods have their own dependency graph (scikit-learn, scipy, etc.)
- Poetry manages isolation — does not pollute main `uv sync` workspace
- Allows testing ranking algorithms without pulling in full backend stack

## Test Configuration

**pytest (backend + mcp_servers):**
- `pyproject.toml` defines dependencies and tool config
- No `pytest.ini` — all config in `pyproject.toml` under `[tool.pytest]` (if present)
- Test discovery: `test_*.py` and `*_test.py` by default

**Playwright (frontend/e2e):**
- `frontend/playwright.config.ts` configures:
  - `webServer`: Starts production build on port 4173 before tests
  - `testDir`: Points to `e2e/` directory

**Vitest (frontend/src):**
- Configuration in `vite.config.ts` (bundled with SvelteKit)
- Uses jsdom for DOM testing

## Test Patterns to Follow

**1. Docstring as Test Plan**
Each test function should have a docstring explaining what it tests:
```python
def test_full_envelope_passes_through():
    """Test 1: normalize_output with full envelope passes through unchanged, normalized_fields=[]."""
    # Implementation
```

**2. Minimal Isolation**
Use the smallest app/setup needed for the test:
- Unit test: Just the function
- Router test: `FastAPI()` + `include_router()`, mock MCP calls
- Full stack test: Use integration test suite (separate from unit tests)

**3. Explicit Mocks**
Always mock external dependencies:
- Database calls → mock via `monkeypatch`
- Redis calls → mock via `patch`
- MCP calls → mock via `AsyncMock`
- OAuth → mock `get_oauth_provider`

**4. Assertion Clarity**
Make assertions explicit:
```python
# Good
assert result.answer == "The answer is 42."
assert len(result.sources) == 1

# Avoid
assert result  # Is this checking truthiness or existence?
```

**5. Error Testing**
Test both success and failure paths:
```python
async def test_api_key_credential_returns_configured_header(...):
    """Success: env var present → header returned."""
    ...

async def test_api_key_credential_raises_when_env_missing(...):
    """Failure: env var missing → CredentialMisconfigured."""
    with pytest.raises(CredentialMisconfigured):
        ...
```

## Common Test Issues & Solutions

**Issue: psycopg2 import fails during test discovery**
- Cause: Full app load in test module scope
- Solution: Use minimal `FastAPI()` + `include_router()` (see test_dry_run.py)
- Alternative: Move test to separate module that doesn't import main.py

**Issue: Async test hangs**
- Cause: Forgot `pytestmark = pytest.mark.anyio` or `async def test_*`
- Solution: Add marker to module top; ensure all async calls are awaited

**Issue: Monkeypatch env var doesn't take effect**
- Cause: Module already imported and cached env var
- Solution: Monkeypatch before import, or reload module after patch
- Example:
  ```python
  async def test_api_key_credential_raises_when_env_missing(monkeypatch):
      monkeypatch.delenv("MY_MISSING_KEY", raising=False)  # Delete, not set
      ...
  ```

**Issue: Mock not called as expected**
- Cause: Patching wrong import path
- Solution: Patch where the function is *used*, not where it's defined
- Example: Patch `backend.tool_arena.router.single_mcp_call` in tests that call router, not `backend.tool_arena.client.single_mcp_call`

---

*Testing analysis: 2026-05-11*
