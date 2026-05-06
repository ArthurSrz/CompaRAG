"""Resolution chain for ``EmbeddingConfig.from_env``.

Default behavior is byte-identical to the original (OpenRouter via
OPENROUTER_API_KEY). When EMBEDDING_BASE_URL is set the operator is opting
into a different provider for embeddings only — the API key falls through
EMBEDDING_API_KEY → OPENAI_API_KEY → OPENROUTER_API_KEY.
"""

from __future__ import annotations

import pytest

from mcp_servers.rag_pill.providers.embedding import (
    EmbeddingConfig,
    OPENAI_BASE_URL,
    OPENROUTER_BASE_URL,
)


_ENV_VARS = (
    "EMBEDDING_BASE_URL",
    "EMBEDDING_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Strip every embedding-related var so each test starts from a known state."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_default_is_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    cfg = EmbeddingConfig.from_env()
    assert cfg.api_key == "or-key"
    assert cfg.base_url == OPENROUTER_BASE_URL
    assert cfg.provider_label == "openrouter"


def test_override_with_explicit_embedding_key(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", OPENAI_BASE_URL)
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-explicit")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    cfg = EmbeddingConfig.from_env()
    assert cfg.api_key == "sk-explicit"
    assert cfg.base_url == OPENAI_BASE_URL
    assert cfg.provider_label == "openai"


def test_override_falls_back_to_openai_key(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", OPENAI_BASE_URL)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fallback")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    cfg = EmbeddingConfig.from_env()
    assert cfg.api_key == "sk-fallback"
    assert cfg.provider_label == "openai"


def test_override_falls_back_to_openrouter_key(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://my-proxy.example.com/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    cfg = EmbeddingConfig.from_env()
    assert cfg.api_key == "or-key"
    assert cfg.base_url == "https://my-proxy.example.com/v1"
    assert cfg.provider_label == "custom"


def test_override_without_any_key_raises(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", OPENAI_BASE_URL)
    with pytest.raises(RuntimeError, match="EMBEDDING_BASE_URL"):
        EmbeddingConfig.from_env()


def test_blank_embedding_base_url_falls_back_to_default(monkeypatch):
    """Empty/whitespace EMBEDDING_BASE_URL must not trigger the override path."""
    monkeypatch.setenv("EMBEDDING_BASE_URL", "   ")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    cfg = EmbeddingConfig.from_env()
    assert cfg.base_url == OPENROUTER_BASE_URL
    assert cfg.provider_label == "openrouter"
