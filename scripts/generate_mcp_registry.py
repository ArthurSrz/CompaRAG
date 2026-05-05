"""Generate mcp_servers.json from pill YAMLs + engine metadata + external entries.

Single source of truth replaces hand-mirrored cross-product. Run via:

    python scripts/generate_mcp_registry.py            # write mcp_servers.json
    python scripts/generate_mcp_registry.py --check    # exit 1 if file would change

The generator does NOT import LangChain, LlamaIndex, or any engine framework —
it reads engine facts from mcp_servers/rag_pill/engines/metadata.py. This keeps
CI fast and isolates engine dep failures from registry generation.

Why a generator: the Tool Arena registry is the cross-product
{pill × engine where engine.supports ⊇ {pill.task_type}}. Computing it by hand
is the duplication this generator removes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from pydantic import TypeAdapter

# Allow running as `python scripts/generate_mcp_registry.py` from repo root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp_servers.rag_pill.engines.metadata import ENGINES, EngineMetadata  # noqa: E402
from mcp_servers.rag_pill.schemas import Pill  # noqa: E402

PILLS_DIR = ROOT / "mcp_servers" / "rag_pill" / "pills"
EXTERNAL_PATH = ROOT / "mcp_servers.external.json"
TARGET_PATH = ROOT / "mcp_servers.json"

# Task-type ordering preserved in the generated JSON. Stable order minimizes
# diff churn when pills are added.
TASK_TYPE_ORDER = ("summary", "qa", "extraction")

# Default rag_pill server endpoint. Per-id override is still honored at runtime
# via the MCP_<ID>_URL env var (see backend/tool_arena/config.py:147-155).
RAG_PILL_ENDPOINT = "http://localhost:8012/mcp"


_pill_adapter = TypeAdapter(Pill)


def _load_pills() -> list[Pill]:
    pills: list[Pill] = []
    for path in sorted(PILLS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        pills.append(_pill_adapter.validate_python(data))
    return pills


def _description_for(pill: Pill, engine: EngineMetadata) -> str:
    recipe = pill.display_description or _derive_description(pill)
    return f"{recipe}, {engine.display_label}"


def _derive_description(pill: Pill) -> str:
    """Fallback when a pill lacks display_description — minimal recipe summary."""
    parts = [pill.task_type, f"chunk={pill.chunk_size}"]
    return ", ".join(parts)


def _entry_for(pill: Pill, engine: EngineMetadata) -> dict:
    return {
        "id": f"{pill.name}__{engine.id}",
        "name": engine.name,
        "description": _description_for(pill, engine),
        "endpoint": RAG_PILL_ENDPOINT,
        "transport": "streamablehttp",
        "tools": ["rag_pill_query"],
        "tool_args": {"pill_id": pill.name, "engine_id": engine.id},
        "task_type": pill.task_type,
        "llm_id": f"openrouter/{pill.llm}",
        "sanitize": {
            "url_patterns": [],
            "metadata_keys": [],
            "extra_terms": list(engine.sanitize_terms),
        },
    }


def _generate_internal_entries(pills: list[Pill]) -> list[dict]:
    by_task: dict[str, list[Pill]] = {}
    for pill in pills:
        by_task.setdefault(pill.task_type, []).append(pill)

    entries: list[dict] = []
    for task_type in TASK_TYPE_ORDER:
        for pill in sorted(by_task.get(task_type, []), key=lambda p: p.name):
            for engine in ENGINES:
                if pill.task_type not in engine.supports:
                    continue
                entries.append(_entry_for(pill, engine))
    return entries


def _load_external() -> list[dict]:
    if not EXTERNAL_PATH.exists():
        return []
    return json.loads(EXTERNAL_PATH.read_text())


def build_registry() -> list[dict]:
    pills = _load_pills()
    return _generate_internal_entries(pills) + _load_external()


def render_json(entries: list[dict]) -> str:
    return json.dumps(entries, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if mcp_servers.json differs from generator output",
    )
    args = parser.parse_args()

    rendered = render_json(build_registry())

    if args.check:
        current = TARGET_PATH.read_text() if TARGET_PATH.exists() else ""
        if current != rendered:
            sys.stderr.write(
                "mcp_servers.json is stale — run `make mcp-registry` and commit.\n"
            )
            return 1
        return 0

    TARGET_PATH.write_text(rendered)
    sys.stderr.write(f"wrote {TARGET_PATH.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
