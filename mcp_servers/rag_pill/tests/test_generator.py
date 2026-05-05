"""Generator tests — assert mcp_servers.json is the cross-product of pills × engines.

Drift between the generator output and the committed file is exactly the
class of bug deepening A removes; this test enforces it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.generate_mcp_registry import (
    EXTERNAL_PATH,
    TARGET_PATH,
    build_registry,
    render_json,
)
from mcp_servers.rag_pill.engines.metadata import ENGINES, METADATA_BY_ID


def test_generator_output_matches_committed_file():
    rendered = render_json(build_registry())
    committed = TARGET_PATH.read_text()
    assert rendered == committed, "mcp_servers.json is stale — run `make mcp-registry`"


def test_every_internal_entry_has_supporting_engine():
    """If the generator emits pill__engine, the engine must support that task."""
    entries = build_registry()
    for entry in entries:
        if entry["tools"] != ["rag_pill_query"]:
            continue  # external entry, skip
        engine_id = entry["tool_args"]["engine_id"]
        engine = METADATA_BY_ID[engine_id]
        assert entry["task_type"] in engine.supports


def test_external_entries_passthrough_unchanged():
    """External entries (Clarifeye, etc.) must appear verbatim in the output."""
    external = json.loads(EXTERNAL_PATH.read_text())
    rendered = build_registry()
    rendered_externals = [e for e in rendered if e["tools"] != ["rag_pill_query"]]
    assert rendered_externals == external


def test_yaml_draft_files_are_skipped():
    """A `.yaml.draft` file must not produce arena entries."""
    pills_dir = Path(__file__).resolve().parent.parent / "pills"
    drafts = list(pills_dir.glob("*.yaml.draft"))
    if not drafts:
        pytest.skip("no draft pills present")
    rendered = build_registry()
    for draft in drafts:
        draft_pill_name = draft.name.split(".")[0]
        assert not any(
            e["tool_args"].get("pill_id") == draft_pill_name
            for e in rendered
            if "tool_args" in e
        )


def test_engine_ids_are_unique():
    """Engine ids must be unique — collisions would silently overwrite entries."""
    ids = [e.id for e in ENGINES]
    assert len(ids) == len(set(ids))
