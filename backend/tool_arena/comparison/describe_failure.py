"""
BUT : transformer une exception en une ligne qui nomme la panne réelle,
y compris quand elle est emballée dans un ExceptionGroup ou une chaîne de
causes.

Future home (cf. knowledge-graph/code-ontology.yaml) :
    backend/tool_arena/comparison/describe_failure.py

`str(ExceptionGroup)` names the TaskGroup, never the failure: an MCP call
that dies inside an anyio task group reports "unhandled errors in a
TaskGroup (1 sub-exception)", which says where it broke and nothing about
why. The arena shows that string to an operator on a failed duel, so it has
to carry the sub-exception instead.
"""

from __future__ import annotations

# A chain deep enough to need this is already unreadable; the cap only stops
# a cyclic __context__ from spinning.
_MAX_DEPTH = 5


def describe_failure(exc: BaseException, _depth: int = 0) -> str:
    """Return "Type: message", unwrapped through groups and causes."""
    if _depth >= _MAX_DEPTH:
        return type(exc).__name__

    if isinstance(exc, BaseExceptionGroup):
        inner = "; ".join(
            describe_failure(sub, _depth + 1) for sub in exc.exceptions
        ) or str(exc)
        return f"{type(exc).__name__}: {inner}"

    text = f"{type(exc).__name__}: {exc}"
    # __cause__ is an explicit `raise ... from`; __context__ catches the
    # implicit re-raise, which is how most transport errors arrive.
    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc:
        return f"{text} <- {describe_failure(cause, _depth + 1)}"
    return text
