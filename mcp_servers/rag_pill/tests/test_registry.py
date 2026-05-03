"""PillRegistry — YAML loading, capability filtering, contestant enumeration."""

from pathlib import Path

from mcp_servers.rag_pill.registry import PillRegistry


class _FakeEngine:
    def __init__(self, eid, supports):
        self.id = eid
        self.SUPPORTS = supports

    async def execute(self, pill, task, goal, document_content):
        return ""


def test_loads_starter_pills():
    pills_dir = Path(__file__).resolve().parent.parent / "pills"
    reg = PillRegistry(pills_dir, engines=[_FakeEngine("lc", {"summary", "qa"})])
    assert "summary_default" in reg.pill_ids
    assert "qa_precise" in reg.pill_ids


def test_list_contestants_filters_by_capability():
    pills_dir = Path(__file__).resolve().parent.parent / "pills"
    reg = PillRegistry(
        pills_dir,
        engines=[
            _FakeEngine("lc", {"summary", "qa"}),
            _FakeEngine("li", {"summary"}),
            _FakeEngine("broken", set()),
        ],
    )

    summary_contestants = reg.list_contestants("summary")
    summary_engines = {eid for _, eid in summary_contestants}
    assert summary_engines == {"lc", "li"}

    qa_contestants = reg.list_contestants("qa")
    qa_engines = {eid for _, eid in qa_contestants}
    assert qa_engines == {"lc"}


def test_list_contestants_unknown_task_type_empty():
    pills_dir = Path(__file__).resolve().parent.parent / "pills"
    reg = PillRegistry(pills_dir, engines=[_FakeEngine("lc", {"summary"})])
    assert reg.list_contestants("nonexistent") == []
