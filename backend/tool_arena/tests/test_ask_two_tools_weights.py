"""Dispatcher weighted sampling — over-sample contestants with weight > 1.

The dispatcher draws the racing pair via weighted sampling without replacement
inside a task_type group. Servers default to weight=1.0 (uniform with peers);
contestants we want to over-sample (e.g. Clarifeye) declare weight > 1.0.

Analytical pair-membership probability for 3 servers with weights [1, 1, 3]:
    P(w=3 in pair) = 3/5 + (2/5) * (3/4) = 0.90
    P(w=1 in pair) = 1/5 + (1/5)*(1/4) + (3/5)*(1/2) = 0.55
"""

import random
from collections import Counter
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


def _srv(sid: str, task_type: str | None, weight: float = 1.0) -> MCPServerConfig:
    return MCPServerConfig(
        id=sid,
        name=sid,
        description="",
        endpoint="https://example.com/mcp",
        transport="streamablehttp",
        tools=["rag_pill_query"],
        task_type=task_type,
        weight=weight,
    )


def _wire(mock_registry, *servers):
    by_id = {s.id: s for s in servers}
    mock_registry.server_ids = list(by_id.keys())
    mock_registry.get_server.side_effect = lambda sid: by_id[sid]


async def test_weight_field_defaults_to_one():
    """Backward compat: omitting weight yields 1.0 (uniform with peers)."""
    s = MCPServerConfig(
        id="x",
        name="x",
        description="",
        endpoint="https://example.com/mcp",
        transport="streamablehttp",
    )
    assert s.weight == 1.0


def test_weight_must_be_positive():
    """Schema rejects weight=0 and weight<0 — sampling needs strictly positive mass."""
    from pydantic import ValidationError

    for bad in (0, -1, -0.5):
        with pytest.raises(ValidationError):
            MCPServerConfig(
                id="x",
                name="x",
                description="",
                endpoint="https://example.com/mcp",
                transport="streamablehttp",
                weight=bad,
            )


async def test_dispatcher_oversamples_high_weight_server():
    """With weights [1, 1, 3], the heavy server should appear in the pair
    with probability ~0.90 (analytical), the light ones with ~0.55 each.

    Run many trials and check empirical frequencies converge within ±2%.
    """
    from backend.tool_arena.comparison.ask_two_tools_concurrently import MCPDispatcher

    s_light_a = _srv("light_a", "summary", weight=1.0)
    s_light_b = _srv("light_b", "summary", weight=1.0)
    s_heavy = _srv("heavy", "summary", weight=3.0)

    mock_registry = MagicMock()
    _wire(mock_registry, s_light_a, s_light_b, s_heavy)
    reg = get_readiness_registry()
    for s in (s_light_a, s_light_b, s_heavy):
        reg.set_ready(s.id)

    random.seed(0)
    trials = 5000
    counts: Counter[str] = Counter()

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
        for _ in range(trials):
            a, b = await MCPDispatcher().dispatch(
                task="t", goal="g", session_id="s"
            )
            counts[a.tool_id] += 1
            counts[b.tool_id] += 1

    p_heavy = counts["heavy"] / trials
    p_light_a = counts["light_a"] / trials
    p_light_b = counts["light_b"] / trials

    # Tolerance ±0.025 — generous enough for 5000 trials yet tight enough that
    # a regression to uniform (each ~0.667) would clearly fail.
    assert abs(p_heavy - 0.90) < 0.025, f"P(heavy in pair)={p_heavy:.3f}, expected 0.90"
    assert abs(p_light_a - 0.55) < 0.025, f"P(light_a in pair)={p_light_a:.3f}, expected 0.55"
    assert abs(p_light_b - 0.55) < 0.025, f"P(light_b in pair)={p_light_b:.3f}, expected 0.55"


async def test_dispatcher_uniform_when_weights_equal():
    """Sanity check: with all weights equal, the weighted code path collapses
    to uniform — each server appears in 2/3 of pairs."""
    from backend.tool_arena.comparison.ask_two_tools_concurrently import MCPDispatcher

    servers = [_srv(f"s{i}", "summary", weight=1.0) for i in range(3)]

    mock_registry = MagicMock()
    _wire(mock_registry, *servers)
    reg = get_readiness_registry()
    for s in servers:
        reg.set_ready(s.id)

    random.seed(0)
    trials = 3000
    counts: Counter[str] = Counter()

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
        for _ in range(trials):
            a, b = await MCPDispatcher().dispatch(
                task="t", goal="g", session_id="s"
            )
            counts[a.tool_id] += 1
            counts[b.tool_id] += 1

    for s in servers:
        p = counts[s.id] / trials
        assert abs(p - 2 / 3) < 0.03, f"P({s.id} in pair)={p:.3f}, expected 0.667"
