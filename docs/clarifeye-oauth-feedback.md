# Note to Clarifeye: integrating MCP from a custom client

A quick write-up of what tripped us up wiring CompaRAG to Clarifeye over MCP,
how we got out, and a proposed addition to the docs so the next forward-deployed
engineer doesn't repeat it.

## The struggle

We were not connecting a packaged AI assistant — we were building our own MCP
client (FastAPI backend, multiple Railway replicas, Redis). The current
`docs.clarifeye.ai/guides/mcp-generic` page is written for the drop-in path
(Copilot, Cursor, Claude Desktop), where the host handles OAuth for you. For a
custom integration it leaves out almost everything that matters.

What that cost us, roughly in order:

1. **Wrong flow on the first attempt.** We reached for `client_credentials`
   ("a server calling another server"). Clarifeye binds tokens to a user, so
   only `authorization_code` + `refresh_token` works. Burned a day before we
   reversed it.
2. **Token endpoint not where the SDK expected.** The MCP Python SDK defaults
   to `{server_url}/token`. Clarifeye's is at `/o/token/`, and it isn't
   discoverable until *after* a metadata fetch that itself needs a token.
   We had to override SDK internals (`_refresh_token`) and ship sentinel
   values (`expires_in=0`, empty `access_token`) to force the refresh path on
   the first call.
3. **Storage churn.** First we baked tokens into the Docker image (immutable).
   Then to disk (Railway wipes the filesystem on each deploy). Finally to
   Redis. Each migration broke production differently.
4. **Refresh-token rotation, undocumented.** Clarifeye rotates refresh tokens
   on every refresh and revokes the old one. Our startup code kept restoring
   the original (now-revoked) token from an env var. Worked once, broke on
   the next redeploy. The "fix" we wrote was actually the bug.
5. **Two replicas racing the refresh.** With rotation on, concurrent refreshes
   leave one replica holding a revoked token. Required a Redis distributed
   lock keyed per OAuth client.
6. **Two registry entries, one OAuth client, two token stores.** We registered
   Clarifeye twice (summary + QA tasks). They had separate storage keys and
   refreshed independently, each invalidating the other.
7. **30 s timeout was too short.** `call_agent` does multi-step reasoning and
   routinely needs 60–90 s. Default cut off complex queries.
8. **Silent logs masked everything.** Our `tool_arena` logger had no handlers
   attached in production. We were debugging blind for over a week. Fixing
   logging unblocked the diagnosis of two other bugs.

The deeper reason it took 15+ commits and 5 PRs: **each bug masked the next**.
Silent logs hid the cold-start. Cold-start looked like rotation. The rotation
"fix" was the rotation bug. You couldn't see layer N until layer N-1 was fixed,
and most layers needed a deploy cycle to confirm.

## The solution (what we ended up with)

- `authorization_code` flow run once locally via `scripts/auth_setup.py`; the
  resulting refresh token is seeded into Redis through an admin endpoint.
- `OAuthClientProvider` subclass (`CompaRAGOAuthProvider`) with an explicit
  `token_url` and an override of `_refresh_token` so the SDK uses
  `/o/token/` from the very first call.
- Token storage in Redis, keyed by **OAuth client** (not by registry entry),
  so co-tenant entries share rotation state.
- A Redis distributed lock (`oauth_refresh_lock:{auth_id}`) wraps every refresh
  so multi-replica deploys don't clobber each other.
- OAuth providers pre-warmed at FastAPI startup so the first user request
  doesn't pay the discovery + refresh + MCP-init cost in one timeout window.
- Per-server timeout (120 s for Clarifeye) plus bounded retry on transient
  connection errors only — never on `asyncio.TimeoutError`.
- The env-var bootstrap path was deleted entirely; storage is now the only
  source of truth. An admin re-key endpoint exists for the day rotation goes
  wrong.

Code lives in `backend/tool_arena/auth.py`. The full postmortem is in
`knowledge-graph/2026-05-02-clarifeye-debug.yaml`.

## Proposed addition to the Clarifeye docs

The existing `guides/mcp-generic` page should stay as-is for the drop-in path,
with one yellow callout added:

> ⚠️ **Refresh tokens rotate on every use.** If your platform exports/imports
> tokens, never re-import an old one — it is already revoked. Re-run the auth
> flow instead.

We propose a new sister page, `guides/mcp-custom-client`, drafted below.

---

### `guides/mcp-custom-client.md` (proposed)

````markdown
# Building a custom MCP client

This guide is for engineers integrating Clarifeye into their own backend (a
service, a custom agent, a SaaS) rather than wiring Clarifeye into a packaged
assistant. If you are using Copilot, Claude Desktop, Cursor, or similar, see
[Other platforms](./mcp-generic) instead.

## Required reading before you start

- Use `authorization_code` + `refresh_token`. **There is no `client_credentials`
  path.** Tokens are bound to a Clarifeye user, not to a service account.
- A human runs the auth flow once; your backend stores the resulting refresh
  token. There is no headless "log the server in" alternative.

## Endpoints (do not rely on auto-discovery)

| Purpose       | URL                                              |
|---------------|--------------------------------------------------|
| Authorization | `https://<env>.gcp.clarifeye.ai/o/authorize/`    |
| Token         | `https://<env>.gcp.clarifeye.ai/o/token/`        |
| MCP server    | `https://<env>.gcp.clarifeye.ai/mcp`             |

The token endpoint is **not** at `/token` and **not** at the MCP server root.
Many MCP SDKs default to `{server_url}/token` — pass the token URL explicitly.

## Refresh-token rotation

Every successful refresh returns a new refresh token and immediately revokes
the previous one. This has three consequences:

1. **Your token store is the source of truth.** Never re-seed tokens from an
   env var or config file on startup — you will restore a revoked token.
2. **Use persistent, shared storage.** Not the container filesystem (lost on
   redeploy), not the image (immutable). Redis, Postgres, or a managed
   secret store.
3. **Serialize refreshes across replicas.** Hold a distributed lock keyed per
   OAuth client around the refresh call. Without it, two replicas refreshing
   concurrently leaves one holding a revoked token.

## One token store per OAuth client

If your application uses Clarifeye for several purposes (e.g. summaries and
Q&A as separate registry entries), they must share **one** token store keyed
by the OAuth `client_id`. Otherwise each consumer rotates the token from under
the others.

## Timeouts and retries

- `call_agent` does multi-step reasoning. Use **90–120 s** per call.
- Retry on transient network errors (`ConnectError`, `RemoteProtocolError`,
  `ReadError`) — bounded, e.g. 1 retry.
- Do **not** retry on timeout. It doubles the user's wait without adding
  signal.

## Cold-start

Pre-warm the OAuth provider at app startup by opening one MCP session and
letting it complete metadata discovery + a refresh. Otherwise the first user
request after every deploy pays that cost inside a single timeout window —
the classic "first call always fails, second one works."

## Re-key path

Build an admin endpoint or CLI that re-runs the auth flow and writes a fresh
refresh token to your store. You will need it the first time rotation goes
wrong, and you do not want to be redeploying to recover.

## Reference: Python (mcp SDK)

```python
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata, OAuthClientInformationFull

class ClarifeyeOAuthProvider(OAuthClientProvider):
    """Override _refresh_token to use Clarifeye's /o/token/ endpoint
    even before metadata discovery has run."""

    def __init__(self, token_url: str, **kwargs):
        super().__init__(**kwargs)
        self._token_url = token_url

    async def _refresh_token(self):
        # ...build httpx.Request against self._token_url...
        # See https://github.com/.../examples for full sample.

provider = ClarifeyeOAuthProvider(
    token_url="https://<env>.gcp.clarifeye.ai/o/token/",
    server_url="https://<env>.gcp.clarifeye.ai/mcp",
    client_metadata=OAuthClientMetadata(
        redirect_uris=["http://localhost:9876/callback"],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        client_name="<your app>",
        scope="claudeai openid offline_access",
        token_endpoint_auth_method="client_secret_post",
    ),
    storage=YourRedisTokenStorage(client_id="..."),
    redirect_handler=...,
    callback_handler=...,
)
```

Validated against `mcp-python` ≥ X.Y. On earlier versions the
`_refresh_token` override is required because the SDK does not accept an
explicit `token_url`.

## Troubleshooting

| Symptom                                     | Likely cause                                                      | Fix                                          |
|---------------------------------------------|-------------------------------------------------------------------|----------------------------------------------|
| First call after deploy fails, then works   | OAuth cold-start                                                  | Pre-warm at startup                          |
| Works, then breaks after redeploy           | Tokens on ephemeral storage or env-var bootstrap overwriting them | Move to persistent store; remove re-seeding  |
| Intermittent 401s under load                | Concurrent refresh on multiple replicas                           | Add a distributed refresh lock               |
| Token endpoint returns 404                  | Client hitting `{server}/token`                                   | Configure `/o/token/` explicitly             |
| `call_agent` times out at 30 s              | Default too short for agentic tools                               | Raise per-server timeout to 90–120 s         |
| You see no auth-related logs                | Logger misconfigured in **your** app                              | Verify logs reach your aggregator first      |
````
