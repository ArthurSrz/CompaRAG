"""Shared helpers for the interview (knowledge_capture) test files.

Not named test_*.py so pytest does not collect it. Mirrors the house
patterns: MCPServerConfig factories, mock registry wiring, and an in-memory
Redis stand-in for the tool_arena session store.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from backend.tool_arena.config import MCPServerConfig

INTERVIEW_MODULE = "backend.tool_arena.interview.run_interview_endpoints"
DISPATCHER_MODULE = "backend.tool_arena.comparison.ask_two_tools_concurrently"


def interview_server(sid: str, strategy: str) -> MCPServerConfig:
    return MCPServerConfig(
        id=sid,
        name=sid,
        description="",
        endpoint="https://example.com/mcp",
        transport="streamablehttp",
        tools=["interview_move"],
        tool_args={"strategy": strategy},
        task_type="knowledge_capture",
        llm_id="openrouter/anthropic/claude-haiku-4.5",
    )


def rag_server(sid: str, task_type: str = "qa") -> MCPServerConfig:
    return MCPServerConfig(
        id=sid,
        name=sid,
        description="",
        endpoint="https://example.com/mcp",
        transport="streamablehttp",
        tools=["rag_pill_query"],
        task_type=task_type,
    )


def wire_registry(*servers: MCPServerConfig) -> MagicMock:
    by_id = {s.id: s for s in servers}
    mock_registry = MagicMock()
    mock_registry.server_ids = list(by_id.keys())
    mock_registry.get_server.side_effect = lambda sid: by_id[sid]
    return mock_registry


class FakeSessionStore:
    """In-memory stand-in for store_tool_session / retrieve_tool_session.

    JSON round-trips on write to mimic Redis serialization (catches
    non-serializable state early, like the real store would).
    """

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}

    def store(self, session_hash: str, data: dict) -> None:
        self.sessions[session_hash] = json.loads(json.dumps(data))

    def retrieve(self, session_hash: str) -> dict:
        if session_hash not in self.sessions:
            # Mirror retrieve_tool_session's contract (ValueError on miss).
            raise ValueError(f"Tool arena session not found: {session_hash}")
        return self.sessions[session_hash]


def question_move(text: str) -> dict:
    return {"type": "question", "question": text}


def artifact_move(markdown: str, subtype: str | None = "mental_model") -> dict:
    return {"type": "artifact", "artifact_markdown": markdown, "artifact_subtype": subtype}
