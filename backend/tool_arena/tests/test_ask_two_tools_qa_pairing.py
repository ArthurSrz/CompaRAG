"""Dispatcher QA pairing — symmetric to test_dispatcher_pairs_within_task_type.

The existing test_dispatcher_task_type.py covers:
- 2 summary + 1 qa, no explicit task_type → pairs summaries (`test_dispatcher_pairs_within_task_type`)
- 3 summary + 2 qa with explicit `task_type="qa"` → pairs QAs (`test_dispatcher_honors_explicit_task_type_param`)
- 1 summary + 1 qa → raise (`test_dispatcher_raises_when_no_group_has_two_ready`)

What's missing (and what Phase 13 Wave 1 needs) is the QA-symmetric of the
first case: 2 qa + 1 summary, no explicit task_type → pairs the two QAs
(only group with >=2 READY). Plus the >=2-per-group invariant when QA
specifically has only one ready server (the failure mode that gates QA
enablement in production).
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


async def test_dispatcher_pairs_two_qa_servers_when_only_qa_group_has_pair():
    """Given two qa servers and one summary server (no explicit task_type),
    the dispatcher must pair the two QAs — summary group has only one,
    QA is the only group with >=2 READY."""
    from backend.tool_arena.comparison.ask_two_tools_concurrently import MCPDispatcher

    s_qa_a = _srv("qa_a", "qa")
    s_qa_b = _srv("qa_b", "qa")
    s_summary = _srv("sum_only", "summary")

    mock_registry = MagicMock()
    _wire(mock_registry, s_qa_a, s_qa_b, s_summary)
    reg = get_readiness_registry()
    for s in (s_qa_a, s_qa_b, s_summary):
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

    assert {a.tool_id, b.tool_id} == {"qa_a", "qa_b"}


async def test_dispatcher_raises_when_requested_qa_has_only_one_ready():
    """Explicit task_type='qa' with only one QA ready (plus two summary)
    must raise InsufficientReadyServersError — never silently cross groups.
    This is the failure mode that gates QA enablement: until two QA pills
    are READY in production, requesting QA cleanly fails."""
    from backend.tool_arena.comparison.ask_two_tools_concurrently import (
        InsufficientReadyServersError,
        MCPDispatcher,
    )

    s_qa_only = _srv("qa_only", "qa")
    s_sum_a = _srv("sum_a", "summary")
    s_sum_b = _srv("sum_b", "summary")

    mock_registry = MagicMock()
    _wire(mock_registry, s_qa_only, s_sum_a, s_sum_b)
    reg = get_readiness_registry()
    for s in (s_qa_only, s_sum_a, s_sum_b):
        reg.set_ready(s.id)

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
                task="t", goal="g", session_id="s", task_type="qa"
            )
