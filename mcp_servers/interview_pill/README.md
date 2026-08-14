# Interview Pill — knowledge-capture MCP server

Two **InterviewStrategies** competing in the arena's `knowledge_capture` task
type. Unlike the RAG tools (same document to both arms), here the **human
expert is the invariant source**: each arm conducts its own independent
interview of the same expert, then produces a markdown **KnowledgeArtifact**
that is blind-compared and voted on.

| Registry id      | Strategy id   | Source skill                                                                 |
|------------------|---------------|------------------------------------------------------------------------------|
| `interview_grill`| `grill`       | Matt Pocock's [grilling](https://github.com/mattpocock/skills/tree/main/skills/productivity) — design-tree frontier rounds |
| `interview_gsd`  | `gsd_discuss` | get-shit-done discuss-phase — adaptive gray-area questioning, lettered options |

The skill instruction files are embedded (near-)verbatim as system prompts in
`prompts/`. Both arms run the **same model** (LLMConstant invariant):
`INTERVIEW_LLM_ID`, default `openrouter/anthropic/claude-haiku-4.5`.

## Statelessness

The server holds zero session state. The backend owns the turn loop, the
Redis session, and the InterviewProtocol (max turns / time budget). Each
`interview_move` call receives one arm's full transcript and returns JSON:

```json
{"type": "question", "question": "..."}
{"type": "artifact", "artifact_markdown": "...", "metadata": {"artifact_subtype": "mental_model"}}
```

`force_artifact=true` (sent by the backend at the cap, the deadline, or on
finish-early) makes the artifact mandatory. Parse failures degrade to a
tolerant fallback — a bad LLM reply never consumes the expert's turn.

## Run locally

```bash
OPENROUTER_API_KEY=... PYTHONPATH=. PORT=8014 python -m mcp_servers.interview_pill.server
curl -s localhost:8014/health   # → OK
```

## Env vars

| Var                  | Default                                   | Purpose                     |
|----------------------|-------------------------------------------|-----------------------------|
| `OPENROUTER_API_KEY` | —                                         | litellm → OpenRouter        |
| `INTERVIEW_LLM_ID`   | `openrouter/anthropic/claude-haiku-4.5`   | LLMConstant for both arms   |
| `INTERVIEW_MAX_TOKENS` | `4096`                                  | completion cap              |
| `PORT`               | `8014`                                    | set by Railway              |

## Deploy

Own Railway service via `railway.interview.toml` (house pattern: one service
per MCP server). After first deploy, set on the **backend** service:
`MCP_INTERVIEW_GRILL_URL` and `MCP_INTERVIEW_GSD_URL` — both pointing to
`https://<service>.up.railway.app/mcp`.
