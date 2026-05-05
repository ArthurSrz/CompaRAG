"""LLM Provider Protocol + OpenRouter adapter.

The Protocol's `invoke` is the only generation seam every engine touches.
Tests stub it with a function that returns a deterministic string; production
wires the OpenRouter adapter.
"""

import os
from typing import Protocol, runtime_checkable

from mcp_servers.rag_pill.schemas import Pill


@runtime_checkable
class LLMProvider(Protocol):
    async def invoke(self, pill: Pill, prompt: str) -> str:
        """Generate a completion for `prompt` using the model named by the pill."""
        ...


class OpenRouterLLM:
    """OpenRouter adapter using the OpenAI-compatible chat completions API.

    Reads the API key from OPENROUTER_API_KEY at construction. Pulls model name,
    temperature, and max_tokens from the pill — pills are the single source of
    LLM-side config so a recipe change never requires a code change.
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self._api_key = api_key or os.environ["OPENROUTER_API_KEY"]
        self._base_url = base_url or "https://openrouter.ai/api/v1"

    async def invoke(self, pill: Pill, prompt: str) -> str:
        # Lazy import: the openai SDK is a transitive dep of langchain-openai
        # but we don't want providers/__init__.py to require it just to import
        # the Protocol type.
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        max_tokens = getattr(pill, "max_output_tokens", 4096)
        response = await client.chat.completions.create(
            model=pill.llm,
            messages=[{"role": "user", "content": prompt}],
            temperature=pill.temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content
        return content or ""
