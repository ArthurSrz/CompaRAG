"""PromptStrategy — pill-aware prompt rendering, decoupled from any engine.

Engines call `render(pill, context, task, goal)` instead of building the
prompt string inline. This concentrates task-type prompt decisions in one
place — adding a new task_type touches one file here, not N engines.
"""

from mcp_servers.rag_pill.schemas import Pill
from mcp_servers.rag_pill.strategies.qa import render as render_qa
from mcp_servers.rag_pill.strategies.summary import render as render_summary
from mcp_servers.rag_pill.strategies.extraction import render as render_extraction

_RENDERERS = {
    "summary": render_summary,
    "qa": render_qa,
    "extraction": render_extraction,
}


def render_prompt(pill: Pill, context: str, task: str, goal: str) -> str:
    """Render the prompt for a pill given retrieved context and the user query."""
    try:
        renderer = _RENDERERS[pill.task_type]
    except KeyError as exc:
        raise ValueError(f"No PromptStrategy for task_type={pill.task_type!r}") from exc
    return renderer(pill, context, task, goal)


__all__ = ["render_prompt"]
