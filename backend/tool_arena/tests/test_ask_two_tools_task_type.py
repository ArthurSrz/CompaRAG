"""Dispatcher fairness — pairing must respect task_type groups.

Pill-based contestants declare a task_type. The dispatcher must group the
READY pool by task_type and only pair two servers within the same group, so
a summary pill is never compared against a QA pill (equifinality invariant).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tool_arena.config import MCPServerConfig
from backend.tool_arena.rag_tool.readiness import (
    _reset_registry_for_tests,
    get_readiness_registry,
)


pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _reset():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _srv(sid: str, task_type: str | None) -> MCPServerConfig:
    return MCPServerConfig(
        id=sid,
        name=sid,
        description="",
        endpoint="https://example.com/mcp",
        transport="streamablehttp",
        tools=["rag_pill_query"],
        task_type=task_type,
    )


def _wire(mock_registry, *servers):
    by_id = {s.id: s for s in servers}
    mock_registry.server_ids = list(by_id.keys())
    mock_registry.get_server.side_effect = lambda sid: by_id[sid]


async def test_dispatcher_pairs_within_task_type():
    """Given two summary servers and one qa server, the dispatcher must
    pair the two summary servers (the qa group has only one member)."""
    from backend.tool_arena.comparison.ask_two_tools_concurrently import MCPDispatcher

    s_summary_a = _srv("sum_a", "summary")
    s_summary_b = _srv("sum_b", "summary")
    s_qa = _srv("qa_only", "qa")

    mock_registry = MagicMock()
    _wire(mock_registry, s_summary_a, s_summary_b, s_qa)
    reg = get_readiness_registry()
    for s in (s_summary_a, s_summary_b, s_qa):
        reg.set_ready(s.id)

    with (
        patch("backend.tool_arena.comparison.ask_two_tools_concurrently.registry", mock_registry),
        patch(
            "backend.tool_arena.comparison.ask_two_tools_concurrently.single_mcp_call",
            new_callable=AsyncMock,
            return_value=("ok", 10),
        ),
        patch(
            "backend.tool_arena.comparison.ask_two_tools_concurrently.sanitize_output",
            side_effect=lambda text, servers: text,
        ),
    ):
        a, b = await MCPDispatcher().dispatch(task="t", goal="g", session_id="s")

    paired_ids = {a.tool_id, b.tool_id}
    assert paired_ids == {"sum_a", "sum_b"}


async def test_dispatcher_raises_when_no_group_has_two_ready():
    """One summary + one qa READY = no group has 2 = raise."""
    from backend.tool_arena.comparison.ask_two_tools_concurrently import (
        InsufficientReadyServersError,
        MCPDispatcher,
    )

    s_sum = _srv("sum_a", "summary")
    s_qa = _srv("qa_a", "qa")

    mock_registry = MagicMock()
    _wire(mock_registry, s_sum, s_qa)
    reg = get_readiness_registry()
    reg.set_ready(s_sum.id)
    reg.set_ready(s_qa.id)

    with (
        patch("backend.tool_arena.comparison.ask_two_tools_concurrently.registry", mock_registry),
        patch(
            "backend.tool_arena.comparison.ask_two_tools_concurrently.single_mcp_call",
            new_callable=AsyncMock,
            return_value=("ok", 10),
        ),
    ):
        with pytest.raises(InsufficientReadyServersError):
            await MCPDispatcher().dispatch(task="t", goal="g", session_id="s")


async def test_dispatcher_honors_explicit_task_type_param():
    """When the caller passes task_type, the dispatcher must pair within that
    group only — even if another group has more contestants."""
    from backend.tool_arena.comparison.ask_two_tools_concurrently import MCPDispatcher

    s_sum_a = _srv("sum_a", "summary")
    s_sum_b = _srv("sum_b", "summary")
    s_sum_c = _srv("sum_c", "summary")
    s_qa_a = _srv("qa_a", "qa")
    s_qa_b = _srv("qa_b", "qa")

    mock_registry = MagicMock()
    _wire(mock_registry, s_sum_a, s_sum_b, s_sum_c, s_qa_a, s_qa_b)
    reg = get_readiness_registry()
    for s in (s_sum_a, s_sum_b, s_sum_c, s_qa_a, s_qa_b):
        reg.set_ready(s.id)

    with (
        patch("backend.tool_arena.comparison.ask_two_tools_concurrently.registry", mock_registry),
        patch(
            "backend.tool_arena.comparison.ask_two_tools_concurrently.single_mcp_call",
            new_callable=AsyncMock,
            return_value=("ok", 10),
        ),
        patch(
            "backend.tool_arena.comparison.ask_two_tools_concurrently.sanitize_output",
            side_effect=lambda text, servers: text,
        ),
    ):
        a, b = await MCPDispatcher().dispatch(
            task="t", goal="g", session_id="s", task_type="qa"
        )

    assert {a.tool_id, b.tool_id} == {"qa_a", "qa_b"}


async def test_dispatcher_raises_when_explicit_task_type_has_no_pair():
    """Requesting task_type=extraction when no extraction servers exist must
    raise rather than silently fall back to a different group."""
    from backend.tool_arena.comparison.ask_two_tools_concurrently import (
        InsufficientReadyServersError,
        MCPDispatcher,
    )

    s_sum_a = _srv("sum_a", "summary")
    s_sum_b = _srv("sum_b", "summary")

    mock_registry = MagicMock()
    _wire(mock_registry, s_sum_a, s_sum_b)
    reg = get_readiness_registry()
    reg.set_ready(s_sum_a.id)
    reg.set_ready(s_sum_b.id)

    with (
        patch("backend.tool_arena.comparison.ask_two_tools_concurrently.registry", mock_registry),
        patch(
            "backend.tool_arena.comparison.ask_two_tools_concurrently.single_mcp_call",
            new_callable=AsyncMock,
            return_value=("ok", 10),
        ),
    ):
        with pytest.raises(InsufficientReadyServersError):
            await MCPDispatcher().dispatch(
                task="t", goal="g", session_id="s", task_type="extraction"
            )


async def test_legacy_servers_form_their_own_group():
    """Servers without task_type (None) are paired together — backward compat."""
    from backend.tool_arena.comparison.ask_two_tools_concurrently import MCPDispatcher

    s_legacy_a = _srv("legacy_a", None)
    s_legacy_b = _srv("legacy_b", None)
    s_summary = _srv("sum_only", "summary")

    mock_registry = MagicMock()
    _wire(mock_registry, s_legacy_a, s_legacy_b, s_summary)
    reg = get_readiness_registry()
    for s in (s_legacy_a, s_legacy_b, s_summary):
        reg.set_ready(s.id)

    with (
        patch("backend.tool_arena.comparison.ask_two_tools_concurrently.registry", mock_registry),
        patch(
            "backend.tool_arena.comparison.ask_two_tools_concurrently.single_mcp_call",
            new_callable=AsyncMock,
            return_value=("ok", 10),
        ),
        patch(
            "backend.tool_arena.comparison.ask_two_tools_concurrently.sanitize_output",
            side_effect=lambda text, servers: text,
        ),
    ):
        a, b = await MCPDispatcher().dispatch(task="t", goal="g", session_id="s")

    assert {a.tool_id, b.tool_id} == {"legacy_a", "legacy_b"}
