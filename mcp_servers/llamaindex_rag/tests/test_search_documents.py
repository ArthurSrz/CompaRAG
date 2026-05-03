"""RED → GREEN test for search_documents tutorial-shape implementation."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.anyio
async def test_search_documents_calls_aquery_and_returns_str(monkeypatch):
    import server

    fake_response = MagicMock()
    fake_response.__str__ = lambda self: "Paul Graham painted in college."

    async def fake_aquery(q):
        assert isinstance(q, str)
        return fake_response

    fake_engine = MagicMock()
    fake_engine.aquery = fake_aquery
    monkeypatch.setattr(server, "query_engine", fake_engine)

    result = await server.search_documents("What did the author do in college?")
    assert isinstance(result, str)
    assert "Paul Graham" in result


@pytest.fixture
def anyio_backend():
    return "asyncio"
