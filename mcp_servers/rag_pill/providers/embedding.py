"""Embedding provider config — shared by every engine that builds its own embedder."""

import os
from dataclasses import dataclass

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class EmbeddingConfig:
    api_key: str
    base_url: str = OPENROUTER_BASE_URL
    provider_label: str = "openrouter"

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        """Resolve the embedding provider from env vars.

        Default: OpenRouter via ``OPENROUTER_API_KEY`` — byte-identical to the
        original behavior. When ``EMBEDDING_BASE_URL`` is set, the operator is
        opting in to a different provider (e.g. OpenAI direct) for embeddings
        only; LLM calls keep using OpenRouter via ``OPENROUTER_API_KEY``.

        Resolution chain:
          1. ``EMBEDDING_BASE_URL`` set → use it; key from
             ``EMBEDDING_API_KEY`` || ``OPENAI_API_KEY`` || ``OPENROUTER_API_KEY``.
          2. otherwise → OpenRouter default with ``OPENROUTER_API_KEY``.
        """
        override_url = os.environ.get("EMBEDDING_BASE_URL", "").strip()
        if override_url:
            api_key = (
                os.environ.get("EMBEDDING_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
                or os.environ.get("OPENROUTER_API_KEY")
            )
            if not api_key:
                raise RuntimeError(
                    "EMBEDDING_BASE_URL is set but no API key is available "
                    "(checked EMBEDDING_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY)."
                )
            label = "openai" if override_url.rstrip("/").endswith("api.openai.com/v1") else "custom"
            return cls(api_key=api_key, base_url=override_url, provider_label=label)

        return cls(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url=OPENROUTER_BASE_URL,
            provider_label="openrouter",
        )
