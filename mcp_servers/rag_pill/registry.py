"""PillRegistry — loads pill YAMLs and engine adapters, exposes contestants."""

from pathlib import Path

import yaml
from pydantic import TypeAdapter

from mcp_servers.rag_pill.engines.base import RAGEngine
from mcp_servers.rag_pill.schemas import Pill

_pill_adapter = TypeAdapter(Pill)


class PillRegistry:
    def __init__(self, pills_dir: Path, engines: list[RAGEngine]) -> None:
        self._pills: dict[str, Pill] = {}
        for path in sorted(pills_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            pill = _pill_adapter.validate_python(data)
            self._pills[pill.name] = pill
        self._engines: dict[str, RAGEngine] = {e.id: e for e in engines}

    def get_pill(self, pill_id: str) -> Pill:
        return self._pills[pill_id]

    def get_engine(self, engine_id: str) -> RAGEngine:
        return self._engines[engine_id]

    def list_contestants(self, task_type: str) -> list[tuple[str, str]]:
        """All (pill_id, engine_id) pairs whose engine supports the task_type."""
        out: list[tuple[str, str]] = []
        for pill_id, pill in self._pills.items():
            if pill.task_type != task_type:
                continue
            for engine_id, engine in self._engines.items():
                if task_type in engine.SUPPORTS:
                    out.append((pill_id, engine_id))
        return out

    @property
    def pill_ids(self) -> list[str]:
        return list(self._pills.keys())

    @property
    def engine_ids(self) -> list[str]:
        return list(self._engines.keys())
