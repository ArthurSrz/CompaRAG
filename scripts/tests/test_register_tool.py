"""Tests for scripts/register_tool.py.

Lock in the two invariants that drift broke in the past:
  1. New tools land in ``mcp_servers.external.json`` — never directly in
     ``mcp_servers.json`` (which is generator output).
  2. Ontology edits are line-level inserts that preserve comments and
     formatting — never a yaml.safe_dump round-trip.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts import register_tool


@pytest.fixture
def manifest() -> dict:
    return {
        "tool_id": "demo_tool",
        "display_name": "Demo Tool",
        "goal": "Outil de démonstration — première ligne descriptive.\nDeuxième ligne ignorée.",
        "endpoint": "http://localhost:9999/mcp",
        "exposes": [{"name": "rag_query"}],
        "task_type": "qa",
        "provider": "openrouter",
        "sanitize": {
            "url_patterns": [],
            "metadata_keys": [],
            "extra_terms": ["Demo"],
        },
    }


def test_manifest_to_entry_shape(manifest):
    entry = register_tool.manifest_to_entry(manifest)
    assert entry["id"] == "demo_tool"
    assert entry["name"] == "Demo Tool"
    assert entry["description"].startswith("Outil de démonstration")
    assert entry["tools"] == ["rag_query"]
    assert entry["task_type"] == "qa"
    assert entry["transport"] == "streamablehttp"
    assert "Demo" in entry["sanitize"]["extra_terms"]


def test_upsert_external_adds_then_updates(tmp_path: Path, manifest):
    external = tmp_path / "external.json"
    external.write_text("[]\n")

    assert register_tool.upsert_external_registry(manifest, target=external) == "added"
    contents = json.loads(external.read_text())
    assert len(contents) == 1
    assert contents[0]["id"] == "demo_tool"

    manifest["display_name"] = "Demo Tool v2"
    assert register_tool.upsert_external_registry(manifest, target=external) == "updated"
    contents = json.loads(external.read_text())
    assert len(contents) == 1
    assert contents[0]["name"] == "Demo Tool v2"


def test_upsert_external_preserves_utf8(tmp_path: Path, manifest):
    external = tmp_path / "external.json"
    external.write_text("[]\n")
    register_tool.upsert_external_registry(manifest, target=external)
    raw = external.read_text()
    assert "démonstration" in raw, "accents must be UTF-8, not \\u-escaped"


def _ontology_fixture() -> str:
    return (
        "# Top-of-file comment that yaml.safe_dump would erase.\n"
        "ontology:\n"
        "  date: 2026-05-18\n"
        "\n"
        "# Section comment above the entities list.\n"
        "entities:\n"
        "  - id: rag_tool\n"
        "    type: DomainEntity\n"
        "    metadata:\n"
        "      currently_known_instances:\n"
        '        - "summary_default__langchain (paragraph summary via LangChain+FAISS)"\n'
        '        - "qa_broad__chroma_baseline (broad QA via Chroma baseline)"\n'
        "\n"
        "  - id: rag_engine\n"
        "    type: DomainEntity\n"
    )


def test_insert_ontology_line_preserves_comments(tmp_path: Path, manifest):
    onto = tmp_path / "code-ontology.yaml"
    onto.write_text(_ontology_fixture())

    result = register_tool.insert_ontology_line(manifest, ontology_path=onto)
    assert result == "inserted"

    text = onto.read_text()
    assert "# Top-of-file comment" in text, "comments must survive"
    assert "# Section comment" in text, "comments must survive"
    assert (
        '        - "demo_tool (Outil de démonstration — première ligne descriptive.)"'
        in text
    )

    # Still valid YAML
    data = yaml.safe_load(text)
    rag_tool = next(e for e in data["entities"] if e["id"] == "rag_tool")
    instances = rag_tool["metadata"]["currently_known_instances"]
    assert any(line.startswith("demo_tool") for line in instances)
    assert len(instances) == 3, "should append, not replace"


def test_insert_ontology_line_is_idempotent(tmp_path: Path, manifest):
    onto = tmp_path / "code-ontology.yaml"
    onto.write_text(_ontology_fixture())

    register_tool.insert_ontology_line(manifest, ontology_path=onto)
    text_after_first = onto.read_text()

    result = register_tool.insert_ontology_line(manifest, ontology_path=onto)
    assert result == "duplicate"
    assert onto.read_text() == text_after_first, "second insert must be a no-op"


def test_insert_ontology_line_inserts_at_list_end(tmp_path: Path, manifest):
    onto = tmp_path / "code-ontology.yaml"
    onto.write_text(_ontology_fixture())

    register_tool.insert_ontology_line(manifest, ontology_path=onto)

    lines = onto.read_text().splitlines()
    last_inst_idx = max(
        i for i, ln in enumerate(lines) if ln.startswith("        - ")
    )
    rag_engine_idx = next(
        i for i, ln in enumerate(lines) if "id: rag_engine" in ln
    )
    assert last_inst_idx < rag_engine_idx, "new line must stay inside rag_tool section"
    assert "demo_tool" in lines[last_inst_idx]
