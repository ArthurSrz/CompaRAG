"""qa_broad pill — the second QA contestant.

Adds a deliberately contrasting QA recipe to the pill registry so the
dispatcher's `>=2 READY servers per task_type group` invariant is satisfiable
for QA. The contrast (top_k=8, rerank=true, temperature=0.2) is the
equifinality variant the arena exposes versus qa_precise.
"""

from pathlib import Path

from mcp_servers.rag_pill.registry import PillRegistry


class _FakeEngine:
    def __init__(self, eid: str, supports: set[str]) -> None:
        self.id = eid
        self.SUPPORTS = supports

    async def execute(self, pill, task, goal, document_content):  # pragma: no cover
        return ""


def test_qa_broad_pill_loads_with_expected_fields() -> None:
    pills_dir = Path(__file__).resolve().parent.parent / "pills"
    reg = PillRegistry(pills_dir, engines=[_FakeEngine("any", {"qa"})])

    assert "qa_broad" in reg.pill_ids, (
        f"qa_broad pill missing from registry. ids={reg.pill_ids}"
    )

    pill = reg.get_pill("qa_broad")
    assert pill.task_type == "qa"
    assert pill.top_k == 8
    assert pill.rerank is True
    assert pill.cite_sources is True
    assert pill.temperature == 0.2
