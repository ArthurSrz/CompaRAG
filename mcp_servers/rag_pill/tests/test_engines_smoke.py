"""Engine smoke tests — exercise each engine end-to-end against the bundled
corpus. Embeddings are real OpenRouter calls; LLM is a CapturingLLM stub.

Behaviour matrix (parametrized over every supported engine class):
- B1: retrieves from corpus when document_content == ""
- B2: retrieves from uploaded document when one is provided
- B3: respects pill.top_k (more chunks → more `---` separators in context)
- B4: routes the rendered prompt through LLMProvider.invoke exactly once

Adding a new engine = adding one entry to ENGINES_UNDER_TEST. The matrix
runs automatically. This is the test surface deepening B + C were built to
enable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.tool_arena.document.read_uploaded_file_as_text import extract_text
from mcp_servers.rag_pill.engines import (
    ChromaBaselineEngine,
    HaystackEngine,
    LangChainEngine,
    LlamaIndexEngine,
    TxtaiEngine,
)
from mcp_servers.rag_pill.providers import OpenRouterLLM
from mcp_servers.rag_pill.schemas import QAPill

_FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "tool_arena"
    / "tests"
    / "fixtures"
)
# The known sentence inside both sample.pdf and sample.docx (built in
# backend/tool_arena/tests/fixtures/) — used as a tracer through the
# extraction → chunking → retrieval → prompt pipeline.
EXTRACTED_TRACER = "marmot"


pytestmark = pytest.mark.anyio


ENGINES_UNDER_TEST = [
    pytest.param(ChromaBaselineEngine, id="chroma"),
    pytest.param(HaystackEngine, id="haystack"),
    pytest.param(TxtaiEngine, id="txtai"),
]


def _qa_pill(top_k: int = 3) -> QAPill:
    return QAPill(
        name="smoke",
        task_type="qa",
        top_k=top_k,
        rerank=False,
        cite_sources=False,
        chunk_size=400,
        chunk_overlap=40,
        temperature=0.0,
    )


@pytest.mark.parametrize("engine_cls", ENGINES_UNDER_TEST)
async def test_retrieves_from_corpus_and_calls_llm(
    engine_cls, cache, capturing_llm, embedding_config
):
    engine = engine_cls(cache, llm=capturing_llm, embedding_config=embedding_config)
    pill = _qa_pill()

    answer = await engine.execute(
        pill, task="What is", goal="async/await in Python?", document_content=""
    )

    # B4: LLM routed through exactly once with the same pill.
    assert answer == "stub-answer"
    assert len(capturing_llm.calls) == 1
    sent_pill, sent_prompt = capturing_llm.calls[0]
    assert sent_pill is pill
    # B1: corpus retrieval populates the Context section.
    assert "Context:" in sent_prompt
    context_after = sent_prompt.split("Context:", 1)[1]
    assert "async" in context_after.lower()


@pytest.mark.parametrize("engine_cls", ENGINES_UNDER_TEST)
async def test_retrieves_from_uploaded_document(
    engine_cls, cache, capturing_llm, embedding_config
):
    engine = engine_cls(cache, llm=capturing_llm, embedding_config=embedding_config)
    pill = _qa_pill()
    # ZORBLIX is a nonsense token guaranteed not to appear in the bundled corpus,
    # so its presence in the prompt proves retrieval sourced the uploaded doc.
    uploaded = (
        "ZORBLIX is a fictional protocol for synchronizing penguins across timezones. "
        "ZORBLIX uses a 7-bit checksum and runs over UDP port 4242. "
        "The ZORBLIX handshake is initiated by the colder party."
    )

    await engine.execute(
        pill, task="What is", goal="ZORBLIX?", document_content=uploaded
    )

    sent_prompt = capturing_llm.calls[0][1]
    assert "ZORBLIX" in sent_prompt


@pytest.mark.parametrize("engine_cls", ENGINES_UNDER_TEST)
async def test_end_to_end_real_llm_returns_grounded_answer(
    engine_cls, cache, embedding_config
):
    """Full live run: real OpenRouter embeddings + real OpenRouter LLM.

    Asserts the engine produces a non-empty answer that references the
    uploaded document. ZORBLIX is a fabricated entity, so the LLM can only
    mention it correctly if the retrieved context surfaced it — this proves
    the full pipeline (chunk → embed → retrieve → prompt → generate) works
    on the live stack.
    """
    real_llm = OpenRouterLLM()
    engine = engine_cls(cache, llm=real_llm, embedding_config=embedding_config)
    pill = _qa_pill()
    uploaded = (
        "ZORBLIX is a fictional protocol for synchronizing penguins across timezones. "
        "ZORBLIX uses a 7-bit checksum and runs over UDP port 4242. "
        "The ZORBLIX handshake is initiated by the colder party."
    )

    answer = await engine.execute(
        pill,
        task="What",
        goal="port does ZORBLIX use?",
        document_content=uploaded,
    )

    assert answer.strip(), "LLM returned an empty answer"
    # The grounded fact "4242" comes only from the uploaded document; if the
    # LLM mentions it, the retrieval pipeline produced usable context.
    assert "4242" in answer


# Full pill matrix: every engine the rag_pill server can register.
# Engines whose framework lib is missing skip gracefully (their SUPPORTS
# set is empty when _AVAILABLE is False), mirroring production where each
# engine is shipped in its own image.
ALL_ENGINES = [
    pytest.param(ChromaBaselineEngine, id="chroma"),
    pytest.param(HaystackEngine, id="haystack"),
    pytest.param(TxtaiEngine, id="txtai"),
    pytest.param(LangChainEngine, id="langchain"),
    pytest.param(LlamaIndexEngine, id="llamaindex"),
]


@pytest.mark.parametrize(
    "fixture_name",
    [pytest.param("sample.pdf", id="pdf"), pytest.param("sample.docx", id="docx")],
)
@pytest.mark.parametrize("engine_cls", ALL_ENGINES)
async def test_engine_handles_extracted_document(
    engine_cls, fixture_name, cache, capturing_llm, embedding_config
):
    """Each engine accepts a string produced by backend extraction of a
    real .pdf / .docx upload, runs the full chunk→embed→retrieve→prompt
    pipeline, and routes the LLM call through CapturingLLM exactly once
    with the extracted content actually present in the prompt context.

    The fixtures are the same ones used by the backend extractor tests
    (backend/tool_arena/tests/fixtures/) — both contain the sentence
    "The marmot inspects the equifinality of every tool."
    """
    if not engine_cls.SUPPORTS:
        pytest.skip(f"{engine_cls.__name__} framework lib not installed")

    raw = (_FIXTURES / fixture_name).read_bytes()
    document_content = extract_text(fixture_name, raw)
    assert EXTRACTED_TRACER in document_content, (
        f"extractor lost the tracer — extracted text was: {document_content!r}"
    )

    engine = engine_cls(cache, llm=capturing_llm, embedding_config=embedding_config)
    pill = _qa_pill()

    answer = await engine.execute(
        pill,
        task="What does the marmot",
        goal="inspect?",
        document_content=document_content,
    )

    assert answer == "stub-answer", (
        f"{engine_cls.__name__} did not invoke the LLM stub for {fixture_name}"
    )
    assert len(capturing_llm.calls) == 1, (
        f"{engine_cls.__name__} called LLM {len(capturing_llm.calls)} times for {fixture_name}"
    )
    sent_prompt = capturing_llm.calls[0][1]
    assert EXTRACTED_TRACER in sent_prompt.lower(), (
        f"{engine_cls.__name__} did not surface extracted '{EXTRACTED_TRACER}' "
        f"into the prompt for {fixture_name}; prompt was: {sent_prompt!r}"
    )


@pytest.mark.parametrize("engine_cls", ENGINES_UNDER_TEST)
async def test_top_k_changes_context_size(
    engine_cls, cache, capturing_llm, embedding_config
):
    """Higher top_k → more retrieved chunks → more `---` separators."""
    blocks = [
        f"Chunk {i}: alpha bravo charlie delta echo foxtrot golf hotel."
        for i in range(20)
    ]
    uploaded = "\n\n".join(blocks)

    small = engine_cls(cache, llm=capturing_llm, embedding_config=embedding_config)
    await small.execute(_qa_pill(top_k=1), task="alpha", goal="bravo", document_content=uploaded)
    small_prompt = capturing_llm.calls[-1][1]

    big = engine_cls(cache, llm=capturing_llm, embedding_config=embedding_config)
    await big.execute(_qa_pill(top_k=8), task="alpha", goal="bravo", document_content=uploaded)
    big_prompt = capturing_llm.calls[-1][1]

    assert big_prompt.count("---") > small_prompt.count("---")
