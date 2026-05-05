"""Test fixtures for engine smoke tests.

Engines are exercised end-to-end against real OpenRouter embeddings (slow
but high-fidelity) with a stub LLMProvider that captures the rendered
prompt without burning generation tokens.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from mcp_servers.rag_pill.cache import IndexCache
from mcp_servers.rag_pill.providers import EmbeddingConfig
from mcp_servers.rag_pill.schemas import Pill


load_dotenv(override=False)


class CapturingLLM:
    """LLMProvider stub — records every invocation so tests can assert on prompts."""

    def __init__(self, response: str = "stub-answer") -> None:
        self.response = response
        self.calls: list[tuple[Pill, str]] = []

    async def invoke(self, pill: Pill, prompt: str) -> str:
        self.calls.append((pill, prompt))
        return self.response


@pytest.fixture
def capturing_llm() -> CapturingLLM:
    return CapturingLLM()


@pytest.fixture
def cache() -> IndexCache:
    return IndexCache(max_entries=4)


@pytest.fixture
def embedding_config() -> EmbeddingConfig:
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set — skipping engine smoke tests")
    return EmbeddingConfig.from_env()
