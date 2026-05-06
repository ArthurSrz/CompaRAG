"""Pill schemas — discriminated union on task_type."""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Discriminator, Field, field_validator


class BasePill(BaseModel):
    """Fields shared by every pill regardless of task_type."""

    name: str
    # Recipe-side display string used by the Tool Arena registry generator.
    # Engine-side label (e.g. "LangChain + FAISS") is appended at generation
    # time, so this field captures only the recipe facts: "Paragraphe,
    # compression 20%". Optional — falls back to a derived string if absent.
    display_description: str | None = None
    llm: str = "mistralai/mistral-medium-3.1"
    embedder: str = "openai/text-embedding-3-small"

    @field_validator("embedder", mode="before")
    @classmethod
    def _strip_provider_prefix(cls, v: str) -> str:
        # OpenRouter's embeddings endpoint rejects provider-prefixed model IDs
        # (e.g. "openai/text-embedding-3-small"). Strip once at parse time so
        # engines always receive the bare model name.
        return v.split("/", 1)[-1] if isinstance(v, str) else v
    chunk_size: int = 500
    chunk_overlap: int = 50
    temperature: float = 0.2


class SummaryPill(BasePill):
    task_type: Literal["summary"]
    compression_ratio: float = 0.2
    style: Literal["bullet", "paragraph"] = "paragraph"
    max_output_tokens: int = 1024


class QAPill(BasePill):
    task_type: Literal["qa"]
    top_k: int = 3
    rerank: bool = False
    cite_sources: bool = True


class ExtractionPill(BasePill):
    task_type: Literal["extraction"]
    output_schema: dict
    top_k: int = 5


Pill = Annotated[
    Union[SummaryPill, QAPill, ExtractionPill],
    Field(discriminator="task_type"),
]
