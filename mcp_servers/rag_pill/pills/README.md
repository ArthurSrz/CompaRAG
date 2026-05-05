# Pills

Each `*.yaml` here is a recipe that the `rag_pill` MCP server can execute on
any compatible engine. The Tool Arena registry generator
(`scripts/generate_mcp_registry.py`) emits one entry per `(pill × engine)` pair
where `engine.supports ⊇ {pill.task_type}`.

## To add a pill

1. Drop a YAML in this directory.
2. Run `make mcp-registry` to refresh `mcp_servers.json`.
3. Review the diff — every new `pill_id__engine_id` row is a new arena
   contestant, so confirm you're ready to ship that.
4. Commit both the YAML and the regenerated JSON.

## To stage a pill without exposing it

Rename it `<name>.yaml.draft`. The registry's `glob("*.yaml")` skips it, so
it is neither a callable pill nor an arena contestant. Use this when a recipe
is still being tuned. Promote by renaming back to `.yaml` and regenerating.
