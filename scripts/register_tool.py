#!/usr/bin/env python3
"""
BUT : enregistrer un nouveau RAGTool standalone (externe) dans l'arène en
une commande.

Lit ``mcp_servers/<slug>/tool.manifest.yaml`` et met à jour :

- ``mcp_servers.external.json`` (source de vérité pour les outils standalone),
- ``mcp_servers.json`` (régénéré via ``scripts/generate_mcp_registry.py``),
- ``knowledge-graph/code-ontology.yaml`` (insertion d'une ligne dans
  ``rag_tool.metadata.currently_known_instances`` — édition texte, sans
  re-sérialisation, pour préserver commentaires et formatage).

NB : les outils ``rag_pill`` (pills × engines) ne passent PAS par ce script
— ils sont matérialisés à partir de ``mcp_servers/rag_pill/pills/*.yaml``
par le générateur.

Usage :
    python scripts/register_tool.py <slug>
    python scripts/register_tool.py --check   # cohérence ontology ↔ mcp_servers.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MCP_SERVERS_JSON = REPO_ROOT / "mcp_servers.json"
MCP_SERVERS_EXTERNAL_JSON = REPO_ROOT / "mcp_servers.external.json"
ONTOLOGY_YAML = REPO_ROOT / "knowledge-graph" / "code-ontology.yaml"
MCP_SERVERS_DIR = REPO_ROOT / "mcp_servers"


def load_manifest(slug: str, base_dir: Path = MCP_SERVERS_DIR) -> dict:
    manifest_path = base_dir / slug / "tool.manifest.yaml"
    if not manifest_path.exists():
        sys.exit(f"[ERROR] Manifest not found at {manifest_path}")
    with manifest_path.open() as fh:
        return yaml.safe_load(fh)


def manifest_to_entry(manifest: dict) -> dict:
    """Build the mcp_servers.external.json entry from a tool manifest."""
    return {
        "id": manifest["tool_id"],
        "name": manifest["display_name"],
        "description": manifest["goal"].strip(),
        "endpoint": manifest["endpoint"],
        "transport": "streamablehttp",
        "tools": [exp["name"] for exp in manifest.get("exposes", [])],
        "task_type": manifest.get("task_type"),
        "llm_id": f"{manifest.get('provider', 'openrouter')}/mistralai/mistral-medium-3.1",
        "sanitize": manifest.get(
            "sanitize", {"url_patterns": [], "metadata_keys": [], "extra_terms": []}
        ),
    }


def upsert_external_registry(manifest: dict, target: Path = MCP_SERVERS_EXTERNAL_JSON) -> str:
    """Add/update the tool's entry in mcp_servers.external.json (idempotent).

    Returns "added" or "updated" — useful for tests.
    """
    entries = json.loads(target.read_text()) if target.exists() else []
    entry = manifest_to_entry(manifest)
    existing = {e["id"]: i for i, e in enumerate(entries)}
    if entry["id"] in existing:
        entries[existing[entry["id"]]] = entry
        outcome = "updated"
    else:
        entries.append(entry)
        outcome = "added"
    target.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
    print(
        f"[OK] {outcome.capitalize()} entry in {target.name} for tool_id={entry['id']!r}"
    )
    return outcome


def regenerate_registry() -> None:
    """Run the generator to refresh mcp_servers.json from pills × engines + external."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from scripts.generate_mcp_registry import (  # noqa: E402
        TARGET_PATH,
        build_registry,
        render_json,
    )

    TARGET_PATH.write_text(render_json(build_registry()))
    print(f"[OK] Regenerated {TARGET_PATH.relative_to(REPO_ROOT)}")


_RAG_TOOL_HEADER_RE = re.compile(r"^\s*-\s+id:\s*rag_tool\s*$")
_NEXT_ENTITY_RE = re.compile(r"^\s*-\s+id:\s*\S+")
_INSTANCES_KEY_RE = re.compile(r"^(\s*)currently_known_instances:\s*$")
_LIST_ITEM_RE = re.compile(r"^(\s+)-\s+")


def insert_ontology_line(manifest: dict, ontology_path: Path = ONTOLOGY_YAML) -> str:
    """Insert a description line under rag_tool.currently_known_instances.

    Edits the YAML file as text (line insertion) rather than via yaml.safe_dump,
    which would strip comments and reformat the whole file. Idempotent on
    tool_id. Returns "inserted" or "duplicate".
    """
    tool_id = manifest["tool_id"]
    description = manifest["goal"].strip().splitlines()[0]
    new_value = f'"{tool_id} ({description})"'

    text = ontology_path.read_text()
    trailing_newline = text.endswith("\n")
    lines = text.split("\n")
    if trailing_newline and lines and lines[-1] == "":
        lines.pop()

    rag_tool_idx = next(
        (i for i, ln in enumerate(lines) if _RAG_TOOL_HEADER_RE.match(ln)),
        -1,
    )
    if rag_tool_idx < 0:
        sys.exit("[ERROR] '- id: rag_tool' header not found in ontology")

    key_idx = -1
    key_indent = ""
    for i in range(rag_tool_idx + 1, len(lines)):
        if i != rag_tool_idx and _NEXT_ENTITY_RE.match(lines[i]):
            break
        m = _INSTANCES_KEY_RE.match(lines[i])
        if m:
            key_idx = i
            key_indent = m.group(1)
            break
    if key_idx < 0:
        sys.exit("[ERROR] 'currently_known_instances:' not found under rag_tool entity")

    item_indent: str | None = None
    last_item_idx = key_idx
    for i in range(key_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        line_indent_len = len(lines[i]) - len(lines[i].lstrip())
        if line_indent_len <= len(key_indent):
            break  # left the list — back at key's level or shallower
        m = _LIST_ITEM_RE.match(lines[i])
        if not m:
            break
        if item_indent is not None and m.group(1) != item_indent:
            break  # different sub-list — outside ours
        item_indent = m.group(1)
        last_item_idx = i
        content = lines[i][len(item_indent) + 2 :].strip().strip("'\"")
        if content.startswith(tool_id + " ") or content == tool_id:
            print(f"[OK] {tool_id!r} already in ontology — no change")
            return "duplicate"

    if item_indent is None:
        item_indent = key_indent + "  "
    new_line = f"{item_indent}- {new_value}"
    lines.insert(last_item_idx + 1, new_line)
    out = "\n".join(lines)
    if trailing_newline:
        out += "\n"
    ontology_path.write_text(out)
    print(f"[OK] Added {tool_id!r} to ontology rag_tool entity")
    return "inserted"


def check_consistency() -> int:
    """Verify that every mcp_servers.json entry has a matching ontology line."""
    entries = json.loads(MCP_SERVERS_JSON.read_text())
    with ONTOLOGY_YAML.open() as fh:
        data = yaml.safe_load(fh)
    known_instances: list[str] = []
    for entity in data.get("entities", []):
        if entity.get("id") == "rag_tool":
            known_instances = (
                entity.get("metadata", {}).get("currently_known_instances", [])
            )

    missing = [
        e["id"]
        for e in entries
        if not any(line.startswith(e["id"]) for line in known_instances)
    ]
    if missing:
        print(f"[FAIL] tools in mcp_servers.json missing from ontology: {missing}")
        return 1
    print(
        f"[OK] all {len(entries)} tool(s) in mcp_servers.json are documented in ontology"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register a new standalone RAGTool — writes to "
            "mcp_servers.external.json, regenerates mcp_servers.json, and "
            "inserts an ontology line."
        ),
    )
    parser.add_argument(
        "slug", nargs="?", help="Tool slug (directory under mcp_servers/)"
    )
    parser.add_argument(
        "--check", action="store_true", help="Verify ontology ↔ registry consistency"
    )
    args = parser.parse_args()

    if args.check:
        return check_consistency()

    if not args.slug:
        parser.error("slug required (or --check)")

    manifest = load_manifest(args.slug)
    if manifest.get("tool_id") in (None, "", "TEMPLATE_REPLACE_ME"):
        sys.exit(
            "[ERROR] tool_id is still set to TEMPLATE_REPLACE_ME — "
            "edit tool.manifest.yaml before registering."
        )

    upsert_external_registry(manifest)
    regenerate_registry()
    insert_ontology_line(manifest)
    print(
        "\n[NEXT] Run the regression suite: pytest backend/ mcp_servers/rag_pill/tests\n"
        "       and the OpenRouter check: python scripts/check_openrouter_providers.py"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
