# PageIndex MCP server

Standalone RAGTool wrapping [VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex).
Builds a hierarchical TOC tree of a document and lets a LiteLLM-backed model
reason over the tree to answer a question — no embeddings, no vector store.

## Local dev

```bash
# Submodule init (clones vendor/PageIndex/)
git submodule update --init mcp_servers/pageindex/vendor/PageIndex

# Install deps
pip install -r mcp_servers/pageindex/requirements.txt

# Run
PORT=8013 OPENROUTER_API_KEY=sk-... \
  python -m mcp_servers.pageindex.server
```

Health probe: `curl http://localhost:8013/health` → `OK`.

## Production (Railway)

PageIndex runs as its own Railway service — separate from the backend pod
so its heavy deps (`pymupdf`, `litellm`) don't bloat the backend image.

### One-time setup

1. **Railway dashboard → New service → "Empty service" → connect this repo.**
2. **Settings → Config-as-code → Config File Path:** `railway.pageindex.toml`
   — Railway will then build using `mcp_servers/pageindex/Dockerfile`.
3. **Settings → Variables**, on the PageIndex service:
   - `OPENROUTER_API_KEY` — required (PageIndex's LiteLLM client routes via
     OpenRouter; see `server.py:35-39`).
4. **Settings → Networking → Generate Public Domain** on the PageIndex
   service. Copy the resulting URL.
5. **Backend service → Variables**, add:
   - `MCP_PAGEINDEX_URL=https://<pageindex-service>.up.railway.app/mcp`

   The backend's registry loader (`backend/tool_arena/config.py:164-172`)
   reads `MCP_<TOOL_ID>_URL` env vars and overrides the
   `mcp_servers.json` endpoint at startup. No code change needed.
6. **Redeploy the backend** to pick up the new env var.

### Verifying

After both services are live:

```bash
# PageIndex service is up
curl https://<pageindex-service>.up.railway.app/health     # → OK

# Backend now sees it as READY
curl https://comparag-production.up.railway.app/tool-arena/leaderboard \
  | python -c "import json, sys; print([t['name'] for t in json.load(sys.stdin)])"
```

Once the readiness probe passes, PageIndex starts being paired against
the other `task_type=qa` tools (5 rag_pill engines) in the arena's
fair-matchmaking dispatcher. The first comparison with at least one vote
makes it appear on the leaderboard
(`utils/ranking/tool_compute.py:203-227`).

### Updating PageIndex

`PAGEINDEX_COMMIT` in the Dockerfile pins the upstream SHA. To upgrade:
update both `PAGEINDEX_COMMIT` and the git submodule pointer, then
redeploy the Railway service.
