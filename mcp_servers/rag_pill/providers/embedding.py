"""Embedding provider config — shared by every engine that builds its own embedder."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingConfig:
    api_key: str
    base_url: str = "https://openrouter.ai/api/v1"

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        return cls(api_key=os.environ["OPENROUTER_API_KEY"])
