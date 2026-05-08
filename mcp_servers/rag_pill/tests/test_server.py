"""Retry behavior for the rag_pill server's embedding-failure escape hatch.

The OpenAI Python SDK raises ``ValueError("No embedding data received")``
when the embeddings response carries an empty ``data`` array — observed in
production as transient OpenRouter routing variance. Server wraps
``engine.execute`` in a bounded retry so a single user-facing call survives
a couple of these blips before the error message reaches the arena UI.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mcp_servers.rag_pill import retry as retry_module
from mcp_servers.rag_pill.retry import (
    _is_empty_embedding_data_error,
    execute_with_embedding_retry,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def no_sleep(monkeypatch):
    """Replace asyncio.sleep so retry tests don't actually wait."""
    async def _instant(_seconds):
        return None

    monkeypatch.setattr(retry_module.asyncio, "sleep", _instant)


class _ScriptedEngine:
    """Async engine stub that yields a scripted sequence of outcomes."""

    id = "scripted"

    def __init__(self, outcomes: list) -> None:
        # Each outcome is either an Exception (raised) or a string (returned).
        self._outcomes = list(outcomes)
        self.call_count = 0

    async def execute(self, pill, task, goal, document_content):
        self.call_count += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def fake_pill():
    return SimpleNamespace(embedder="openai/text-embedding-3-small")


# --- _is_empty_embedding_data_error ----------------------------------------


def test_marker_matches_exact_openai_sdk_message():
    assert _is_empty_embedding_data_error(ValueError("No embedding data received"))


def test_marker_matches_when_wrapped_in_context():
    assert _is_empty_embedding_data_error(
        ValueError("openai.embeddings.create: No embedding data received from upstream")
    )


def test_marker_rejects_unrelated_value_error():
    assert not _is_empty_embedding_data_error(ValueError("invalid model"))


def test_marker_rejects_non_value_error():
    assert not _is_empty_embedding_data_error(RuntimeError("No embedding data received"))


# --- execute_with_embedding_retry ------------------------------------------


async def test_retry_then_succeed(no_sleep, fake_pill):
    """Two transient empty-data failures, third attempt returns the answer."""
    engine = _ScriptedEngine([
        ValueError("No embedding data received"),
        ValueError("No embedding data received"),
        "the answer",
    ])
    out = await execute_with_embedding_retry(
        engine, fake_pill, "task", "goal", "doc", max_retries=2
    )
    assert out == "the answer"
    assert engine.call_count == 3


async def test_retry_exhausts_and_reraises(no_sleep, fake_pill):
    engine = _ScriptedEngine([
        ValueError("No embedding data received"),
        ValueError("No embedding data received"),
        ValueError("No embedding data received"),
    ])
    with pytest.raises(ValueError, match="No embedding data received"):
        await execute_with_embedding_retry(
            engine, fake_pill, "task", "goal", "doc", max_retries=2
        )
    assert engine.call_count == 3  # initial + max_retries


async def test_non_matching_exception_is_not_retried(no_sleep, fake_pill):
    """Auth/quota/etc. surface immediately — retrying would just delay the truth."""
    engine = _ScriptedEngine([
        RuntimeError("authentication failed: invalid API key"),
        "should never reach this",
    ])
    with pytest.raises(RuntimeError, match="authentication failed"):
        await execute_with_embedding_retry(
            engine, fake_pill, "task", "goal", "doc", max_retries=5
        )
    assert engine.call_count == 1


async def test_zero_retries_means_one_attempt(no_sleep, fake_pill):
    engine = _ScriptedEngine([ValueError("No embedding data received")])
    with pytest.raises(ValueError):
        await execute_with_embedding_retry(
            engine, fake_pill, "task", "goal", "doc", max_retries=0
        )
    assert engine.call_count == 1


async def test_prod_path_propagates_no_embedding_data_after_retries(
    no_sleep, monkeypatch
):
    """Authentic reproduction of the prod failure mode.

    Mirrors what users see when OpenRouter routes embedding traffic to a
    provider that returns ``200 OK`` with ``data: []`` — the openai SDK
    (>=1.40) raises ``ValueError("No embedding data received")`` from
    ``openai/resources/embeddings.py``. ``execute_with_embedding_retry``
    matches that string, retries with exponential backoff, and re-raises
    the original ValueError once retries are exhausted.

    We monkeypatch ``openai.resources.embeddings.Embeddings.create`` so a
    real ``TxtaiEngine`` exercises the same code path as production but
    deterministically fails — no network, no flaky provider needed.
    """
    txtai = pytest.importorskip("txtai")  # engine is opt-in
    from openai.resources.embeddings import Embeddings

    from mcp_servers.rag_pill.cache import IndexCache
    from mcp_servers.rag_pill.engines import TxtaiEngine
    from mcp_servers.rag_pill.providers import EmbeddingConfig
    from mcp_servers.rag_pill.schemas import QAPill

    def _empty_data(*args, **kwargs):
        # Same exception the openai SDK raises in production when the
        # provider returns 200 OK with an empty data array.
        raise ValueError("No embedding data received")

    monkeypatch.setattr(Embeddings, "create", _empty_data)

    cache = IndexCache(max_entries=1)
    embed_cfg = EmbeddingConfig(
        api_key="dummy", base_url="https://openrouter.ai/api/v1"
    )

    class _StubLLM:
        async def invoke(self, pill, prompt):  # never reached
            return "unreachable"

    engine = TxtaiEngine(cache, llm=_StubLLM(), embedding_config=embed_cfg)
    pill = QAPill(
        name="repro",
        task_type="qa",
        top_k=3,
        rerank=False,
        cite_sources=False,
        chunk_size=400,
        chunk_overlap=40,
        temperature=0.0,
    )

    with pytest.raises(ValueError, match="No embedding data received"):
        await execute_with_embedding_retry(
            engine,
            pill,
            task="What is",
            goal="anything?",
            document_content="some uploaded document content",
            max_retries=2,  # 3 total attempts, identical to prod default
        )


# --- Per-engine retry coverage --------------------------------------------
# Verifies the mitigation strategy fires for every engine, not just the one
# we happened to debug. Two assertions per engine:
#   (1) marker contract — when openai responds with empty data, the engine
#       surfaces a ValueError that ``_is_empty_embedding_data_error`` matches.
#       If an engine wraps the SDK error in its own exception type, retry
#       would silently fail to fire in production.
#   (2) transient recovery — when the flake clears mid-retry, the wrapper
#       lets the engine produce a normal answer.


def _engine_param(name: str):
    """Build a parametrize entry; each importorskip + class lookup happens
    inside the test so missing engine libs skip cleanly."""
    return pytest.param(name, id=name)


_PER_ENGINE_PARAMS = [
    _engine_param("ChromaBaselineEngine"),
    _engine_param("HaystackEngine"),
    _engine_param("TxtaiEngine"),
    _engine_param("LangChainEngine"),
    _engine_param("LlamaIndexEngine"),
]


def _make_engine(class_name: str, cache, llm, embed_cfg):
    pytest.importorskip("openai")
    from mcp_servers.rag_pill import engines as _engines

    cls = getattr(_engines, class_name)
    if not cls.SUPPORTS:
        pytest.skip(f"{class_name} framework lib not installed")
    return cls(cache, llm=llm, embedding_config=embed_cfg)


def _qa_pill_for_repro():
    from mcp_servers.rag_pill.schemas import QAPill

    return QAPill(
        name="repro",
        task_type="qa",
        top_k=3,
        rerank=False,
        cite_sources=False,
        chunk_size=400,
        chunk_overlap=40,
        temperature=0.0,
    )


@pytest.mark.parametrize("engine_class_name", _PER_ENGINE_PARAMS)
async def test_engine_surfaces_marker_when_embeddings_empty(
    no_sleep, monkeypatch, engine_class_name
):
    """Each engine surfaces the SDK marker when the embeddings API returns
    empty data — proving retry.py's matcher will fire for every contestant.
    """
    from openai.resources.embeddings import Embeddings

    from mcp_servers.rag_pill.cache import IndexCache
    from mcp_servers.rag_pill.providers import EmbeddingConfig

    def _empty_data(*args, **kwargs):
        raise ValueError("No embedding data received")

    monkeypatch.setattr(Embeddings, "create", _empty_data)

    class _StubLLM:
        async def invoke(self, pill, prompt):
            return "unreachable"

    cache = IndexCache(max_entries=1)
    embed_cfg = EmbeddingConfig(
        api_key="dummy", base_url="https://openrouter.ai/api/v1"
    )
    engine = _make_engine(engine_class_name, cache, _StubLLM(), embed_cfg)

    raised: BaseException | None = None
    try:
        await engine.execute(
            _qa_pill_for_repro(),
            task="What is",
            goal="anything?",
            document_content="some uploaded document content",
        )
    except BaseException as exc:  # noqa: BLE001 — we want to inspect any error
        raised = exc

    assert raised is not None, (
        f"{engine_class_name} swallowed the empty-embeddings ValueError — "
        "retry.py would never fire."
    )
    assert _is_empty_embedding_data_error(raised), (
        f"{engine_class_name} surfaced {type(raised).__name__}: {raised!r} — "
        "retry.py's marker matcher will not catch this in production."
    )


@pytest.mark.parametrize("engine_class_name", _PER_ENGINE_PARAMS)
async def test_retry_rescues_engine_after_transient_empty_data(
    no_sleep, monkeypatch, engine_class_name
):
    """Once the flake clears mid-retry, the wrapper produces a normal answer
    for every engine — verifies the mitigation actually rescues real engines.
    """
    from openai.resources.embeddings import Embeddings

    from mcp_servers.rag_pill.cache import IndexCache
    from mcp_servers.rag_pill.providers import EmbeddingConfig

    real_create = Embeddings.create
    failures_remaining = {"n": 2}  # fail twice, then let the real call through

    def _flaky(self, *args, **kwargs):
        if failures_remaining["n"] > 0:
            failures_remaining["n"] -= 1
            raise ValueError("No embedding data received")
        return real_create(self, *args, **kwargs)

    monkeypatch.setattr(Embeddings, "create", _flaky)

    if not pytest.importorskip("os") and not False:
        pass
    import os

    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set — needs real embeddings on attempt 3")

    class _StubLLM:
        async def invoke(self, pill, prompt):
            return "rescued-answer"

    cache = IndexCache(max_entries=1)
    embed_cfg = EmbeddingConfig.from_env()
    engine = _make_engine(engine_class_name, cache, _StubLLM(), embed_cfg)

    answer = await execute_with_embedding_retry(
        engine,
        _qa_pill_for_repro(),
        task="What is",
        goal="anything?",
        document_content="ZORBLIX is a fictional protocol used for the test only.",
        max_retries=2,
    )

    assert answer == "rescued-answer", (
        f"{engine_class_name} did not produce a normal answer after retry recovery; "
        f"got {answer!r}"
    )
    assert failures_remaining["n"] == 0, (
        f"{engine_class_name} called embeddings only "
        f"{2 - failures_remaining['n']}/2 expected failure attempts"
    )


def test_default_retries_reads_env(monkeypatch):
    """The module-level default reads RAG_PILL_EMBEDDING_RETRIES at import time."""
    import importlib

    monkeypatch.setenv("RAG_PILL_EMBEDDING_RETRIES", "5")
    reloaded = importlib.reload(retry_module)
    assert reloaded.EMBEDDING_RETRIES == 5
    # Restore default for subsequent tests in this session.
    monkeypatch.setenv("RAG_PILL_EMBEDDING_RETRIES", "2")
    importlib.reload(retry_module)
