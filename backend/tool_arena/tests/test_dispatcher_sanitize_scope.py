"""Regression test: sanitizer must apply patterns from ALL registered servers,
not just the two racing in this round.

Bug observed in prod: user uploads a document mentioning "Clarifeye". When
langchain_rag and llamaindex_rag are randomly picked, Clarifeye's sanitize
extra_terms (["Clarifeye", "clarifeye"]) are NEVER applied because the
dispatcher passes only the 2 racing servers to sanitize_envelope. Result:
"Clarifeye" leaks into the answer text users see, breaking blind comparison.

The blind comparison invariant is: tool identities should never leak,
regardless of which two happen to race.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tool_arena.config import (
    ApiKeyAuth,
    MCPServerConfig,
    SanitizeConfig,
)
from backend.tool_arena.readiness import (
    _reset_registry_for_tests,
    get_readiness_registry,
)


pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _reset_readiness_between_tests():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _server(server_id: str, sanitize: SanitizeConfig | None = None) -> MCPServerConfig:
    return MCPServerConfig(
        id=server_id,
        name=server_id.replace("_", " ").title(),
        description=f"test server {server_id}",
        endpoint=f"https://{server_id}.example.com/mcp",
        transport="streamablehttp",
        auth=ApiKeyAuth(type="api_key", key_env=f"K_{server_id.upper()}", header="Authorization"),
        tools=["*"],
        sanitize=sanitize,
        llm_id="openrouter/mistralai/mistral-small-3.1-24b-instruct",
    )


async def test_sanitize_applies_patterns_from_non_racing_servers():
    """When only 2 of 3 registered servers race, the third's identity terms
    must STILL be redacted from both answers — answers can mention any tool
    name regardless of who's racing (e.g. user document references the
    third tool by name).

    Bug repro: dispatcher.py:103 currently does `servers = [server_a, server_b]`
    and passes only that pair to sanitize_envelope/sanitize_output. The third
    server's `sanitize.extra_terms` are dropped.
    """
    from backend.tool_arena.dispatcher import MCPDispatcher

    server_lc = _server("langchain_rag")
    server_li = _server("llamaindex_rag")
    server_cf = _server(
        "clarifeye",
        sanitize=SanitizeConfig(extra_terms=["Clarifeye", "clarifeye"]),
    )

    mock_registry = MagicMock()
    by_id = {s.id: s for s in (server_lc, server_li, server_cf)}
    mock_registry.server_ids = list(by_id.keys())
    mock_registry.get_server.side_effect = lambda sid: by_id[sid]

    # Realistic scenario: 3 servers registered, only 2 are READY this round.
    # Dispatcher's `len(ready) == 2` branch picks both deterministically.
    # Clarifeye is registered (its sanitize patterns SHOULD apply globally)
    # but not racing.
    reg = get_readiness_registry()
    reg.set_ready(server_lc.id)
    reg.set_ready(server_li.id)
    # clarifeye intentionally left UNKNOWN

    raw_answer = (
        "The Clarifeye platform is a knowledge warehouse. "
        "Clarifeye exposes call_agent and run_tool endpoints."
    )

    with (
        patch("backend.tool_arena.dispatcher.registry", mock_registry),
        patch(
            "backend.tool_arena.dispatcher.single_mcp_call",
            new_callable=AsyncMock,
            return_value=(raw_answer, 100),
        ),
    ):
        call_a, call_b = await MCPDispatcher().dispatch(
            task="summarize", goal="brief", session_id="bug-repro-1",
        )

    assert "Clarifeye" not in call_a.mediated_result, (
        f"BLIND-COMPARISON VIOLATION: 'Clarifeye' leaked into Tool A answer. "
        f"Got: {call_a.mediated_result!r}"
    )
    assert "Clarifeye" not in call_b.mediated_result, (
        f"BLIND-COMPARISON VIOLATION: 'Clarifeye' leaked into Tool B answer. "
        f"Got: {call_b.mediated_result!r}"
    )
    assert "clarifeye" not in call_a.mediated_result.lower().replace("⟨redacted⟩", "")
    assert "clarifeye" not in call_b.mediated_result.lower().replace("⟨redacted⟩", "")
