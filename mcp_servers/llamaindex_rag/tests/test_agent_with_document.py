"""Test FunctionAgent with only search_documents, against a real in-memory document."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_agent_answers_question_about_loaded_document(monkeypatch):
    from llama_index.core import Document, VectorStoreIndex
    from llama_index.core.llms import MockLLM

    import server

    doc_text = (
        "Paul Graham is a programmer and essayist. "
        "In college he studied philosophy and then switched to computer science. "
        "He later co-founded Y Combinator."
    )
    index = VectorStoreIndex.from_documents([Document(text=doc_text)])
    monkeypatch.setattr(server, "query_engine", index.as_query_engine())

    agent = server.build_agent(llm=MockLLM())
    assert agent is not None
    assert any(
        getattr(t, "metadata", None) and t.metadata.name == "search_documents"
        for t in agent.tools
    )
    assert "Résumez le document" in agent.system_prompt

    result = await server.search_documents("What did Paul Graham study in college?")
    assert isinstance(result, str)
    assert len(result) > 0
