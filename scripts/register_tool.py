#!/usr/bin/env python3
"""
BUT : enregistrer un nouveau RAGTool dans l'arène en une commande.

Lit `mcp_servers/<slug>/tool.manifest.yaml`, met à jour `mcp_servers.json`
(ajout de l'entrée) ET `knowledge-graph/code-ontology.yaml` (ajout de
l'entité RAGTool[<slug>]) — pour que la disposition reste alignée avec
l'ontologie sans intervention manuelle.

Usage :
    python scripts/register_tool.py <slug>
    python scripts/register_tool.py --check  # vérifie la cohérence
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MCP_SERVERS_JSON = REPO_ROOT / "mcp_servers.json"
ONTOLOGY_YAML = REPO_ROOT / "knowledge-graph" / "code-ontology.yaml"
MCP_SERVERS_DIR = REPO_ROOT / "mcp_servers"


def load_manifest(slug: str) -> dict:
    manifest_path = MCP_SERVERS_DIR / slug / "tool.manifest.yaml"
    if not manifest_path.exists():
        sys.exit(f"[ERROR] Manifest not found at {manifest_path}")
    with manifest_path.open() as fh:
        return yaml.safe_load(fh)


def upsert_mcp_servers_json(manifest: dict) -> None:
    """Add the tool's entry to mcp_servers.json (idempotent)."""
    entries = json.loads(MCP_SERVERS_JSON.read_text())
    entry = {
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

    # Replace if already present.
    existing_ids = {e["id"]: i for i, e in enumerate(entries)}
    if entry["id"] in existing_ids:
        entries[existing_ids[entry["id"]]] = entry
        print(f"[OK] Updated existing entry for tool_id={entry['id']!r}")
    else:
        entries.append(entry)
        print(f"[OK] Added new entry for tool_id={entry['id']!r}")

    MCP_SERVERS_JSON.write_text(json.dumps(entries, indent=2) + "\n")


def upsert_ontology(manifest: dict) -> None:
    """Append a new RAGTool instance to code-ontology.yaml#rag_tool."""
    with ONTOLOGY_YAML.open() as fh:
        data = yaml.safe_load(fh)

    for entity in data.get("entities", []):
        if entity.get("id") == "rag_tool":
            metadata = entity.setdefault("metadata", {})
            known = metadata.setdefault("currently_known_instances", [])
            entry = f"{manifest['tool_id']} ({manifest['goal'].strip().splitlines()[0]})"
            if not any(line.startswith(manifest["tool_id"]) for line in known):
                known.append(entry)
                print(f"[OK] Added {manifest['tool_id']!r} to ontology RAGTool entity")
            else:
                print(f"[OK] {manifest['tool_id']!r} already in ontology — no change")
            break
    else:
        sys.exit("[ERROR] entity rag_tool not found in code-ontology.yaml")

    ONTOLOGY_YAML.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


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
    print(f"[OK] all {len(entries)} tool(s) in mcp_servers.json are documented in ontology")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register a new RAGTool in mcp_servers.json + ontology",
    )
    parser.add_argument("slug", nargs="?", help="Tool slug (directory under mcp_servers/)")
    parser.add_argument("--check", action="store_true", help="Verify consistency only")
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

    upsert_mcp_servers_json(manifest)
    upsert_ontology(manifest)
    print(
        f"\n[NEXT] Run the regression suite: pytest backend/\n"
        f"       and the OpenRouter check: python scripts/check_openrouter_providers.py"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
