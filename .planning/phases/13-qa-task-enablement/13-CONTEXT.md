# Phase 13: QA Task Enablement — Context

**Gathered:** 2026-05-11
**Status:** Ready for planning
**Source:** Architecture discussion 2026-05-11 (5 deepening candidates ranked; this phase bundles #4 → #1+#3 → #2 → #6 frontend re-enable)

<domain>
## Phase Boundary

Enable the **Q&A task type** end-to-end in the Tool Arena, building on the existing scaffolding (backend already accepts `task_type="qa"`; `qa_precise.yaml` pill exists; UI hides QA pending validation). The phase deepens the `task_type` seam from a shallow string spread across 4 places into a typed `TaskKind` contract, adds a second QA pill so the dispatcher's `>=2 READY servers per group` invariant is satisfiable, introduces a `TaskMediator` per `TaskKind` (so QA gets its own refusal + citation policy without polluting the summary path), and finally re-enables QA in the frontend.

**Out of scope (deferred):**
- Phase 5 (EquifinalityContract value object) — useful but not blocking; opens Phase 14.
- "Extraction" task type — removed from frontend in commit `0e442485`; rebuild later if/when a second extraction pill is authored.
- Document context injection (was originally slated for Phase 12 per `STATE.md`).

</domain>

<decisions>
## Implementation Decisions

### TaskKind taxonomy
- `TaskKind` lives in a new module `backend/tool_arena/task_kind.py` as a Python `Enum` carrying: `id`, `requires_document: bool`, `display_label_key: str` (i18n key), `mediator_id: str`.
- Backwards-compat: `Literal["summary", "qa", "extraction"]` on `CompareRequest` is replaced by `TaskKind` references. Wire-format stays string (the existing `task_type` JSON field).
- Frontend `TaskType` is hand-mirrored as a TS literal union — single import line at the top of `ToolArenaForm.svelte`. (No TS codegen pipeline yet; introducing one is its own phase.)
- Pill YAML `task_type` validates against `TaskKind` at load time in `mcp_servers/rag_pill/registry.py`. Invalid values raise on startup (fail-fast).

### Second QA pill
- New file: `mcp_servers/rag_pill/pills/qa_broad.yaml`. Same `task_type: qa`, but a deliberately contrasting RAG config: `top_k: 8`, `rerank: true`, `temperature: 0.2`, `cite_sources: true`. The contrast is the equifinality variant the arena exposes.
- Both QA pills must reach READY in the readiness registry before the dispatcher accepts `task_type="qa"` — same invariant as summary today (`dispatcher.py:114`).

### TaskMediator seam
- Single interface: `TaskMediator.mediate(envelope: NormalizedEnvelope, task: str, goal: str) -> str` in `backend/tool_arena/task_mediator/__init__.py`.
- Two adapters: `SummaryMediator` (extracted from current `client.py` mediation site) and `QAMediator` (new — system prompt enforces "answer from sources only, refuse if not in context, cite source ids inline").
- Dispatcher selects mediator via `TaskKind.mediator_id` lookup. No `if task_type == ...` branches in `client.py`.

### requires_document contract
- `CompareRequest.model_validator(mode="after")` rejects mismatches: 422 if `task_type=summary` and `document_content == ""`, OR `task_type=qa` and `document_content == ""` (QA still needs a corpus — for v1 we keep "QA over uploaded doc"; QA-over-corpus is a future phase).
- Decision: **QA requires a document in v1**. Rationale: existing pills only know how to RAG over the supplied `document_content`; corpus mode is its own retrieval contract.
- Frontend `requiresDocument = $derived(...)` is removed; replaced with `taskKindTable[selectedTaskType].requiresDocument`.

### Frontend re-enable
- `TaskType` union expands to `'summary' | 'qa'`. Extraction stays out until a second extraction pill exists.
- The `{#if taskTypes.length > 1}` guard naturally surfaces the dropdown again.
- E2E validation via the Chrome DevTools MCP loop documented in `goal_directed_action_world/CLAUDE.md` (upload → set goal → click "COMPARER" → both panes render → vote → reveal).

### Claude's Discretion
- Exact wording of the `QAMediator` system prompt (subject to A/B testing).
- Whether to log `task_kind` on the `ToolVoteRecord` (likely yes — but schema migration is its own task).
- Pill YAML schema version bump if validation logic changes.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Codebase map (just generated)
- `.planning/codebase/ARCHITECTURE.md` — three-router pattern, dispatcher / client / normalizer / sanitizer pipeline.
- `.planning/codebase/STRUCTURE.md` — directory layout, naming conventions.
- `.planning/codebase/CONCERNS.md` — dispatcher pool=2 footgun (`backend/tool_arena/dispatcher.py:133`), rag-pill manual deploy, embedding-validator asymmetry.

### Backend modules to read
- `backend/tool_arena/router.py:229-237` — `CompareRequest` with current `Literal` field.
- `backend/tool_arena/dispatcher.py:60-145` — `dispatch()`, task_type grouping logic, fairness invariant comments.
- `backend/tool_arena/client.py` — mediation call site (`mediated_result`).
- `backend/tool_arena/models.py:37-62` — `MCPToolCall.mediated_result` and `llm_id`.
- `backend/tool_arena/normalizer.py` — `NormalizedEnvelope` shape (mediator input).

### MCP server (rag-pill)
- `mcp_servers/rag_pill/pills/qa_precise.yaml` — existing single QA pill.
- `mcp_servers/rag_pill/pills/summary_default.yaml` — reference shape.
- `mcp_servers/rag_pill/registry.py` — pill loader (where `task_type` validation lands).

### Frontend
- `frontend/src/routes/tool-arena/components/ToolArenaForm.svelte:27-70` — `TaskType` literal, `taskTypes` array, `requiresDocument` derivation, hide-when-one guard.
- `frontend/src/routes/tool-arena/+page.svelte:74` — request body assembly.

### ADRs and prior decisions
- `docs/adr/0001-oauth-rekey-via-admin-endpoint.md` — irrelevant here, but referenced by integration tests via `auth.py`.
- Commit `de5b0372` — QA hidden until end-to-end validated (this phase clears the gate).
- Commit `e0442485` — extraction removed (informs why `TaskKind` enum should start with just `{summary, qa}`).

### Deployment caveat
- `rag-pill` Railway service is **manual-deploy only** (`railway up --service rag-pill`). Adding `qa_broad.yaml` requires this step — call it out in the relevant plan's `<verify>` block.

</canonical_refs>

<specifics>
## Specific Ideas

- `qa_broad.yaml` config draft: `top_k: 8`, `chunk_size: 800`, `chunk_overlap: 100`, `rerank: true`, `temperature: 0.2`, `cite_sources: true`, `llm: mistralai/mistral-medium-3.1`, `embedder: openai/text-embedding-3-small`.
- `QAMediator` prompt skeleton: *"You are a Q&A assistant. Answer the user's question using ONLY the provided sources. Cite source ids inline as `[s1]`, `[s2]`, etc. If the answer is not in the sources, reply exactly: 'Je ne trouve pas la réponse dans le document fourni.' Do not add commentary."*
- Frontend i18n keys: `toolArena.taskType.qa.label`, `.prompt`, `.goalText` — add to all 5 locales (`fr`, `da`, `sv`, `et`, `lt`).
- Integration test: `backend/tool_arena/tests/test_dispatcher_qa_pairing.py` — patch readiness registry with two mocked QA servers, assert dispatcher returns both.
- E2E test addition: extend `frontend/e2e/demo.test.ts` (or new file) with the QA path.

</specifics>

<deferred>
## Deferred Ideas

- **EquifinalityContract value object** (architecture candidate #5) — defer to Phase 14. Becomes attractive once a second non-summary task lives in the codebase.
- **TaskKind codegen pipeline** (Python → TypeScript) — defer until at least one more task type joins. Hand-mirrored union is fine for two.
- **QA-over-corpus retrieval** — requires document_registry hook into RAG engines. Probably Phase 15 (paired with the deferred "Context Injection" phase).
- **Extraction re-enable** — needs a second extraction pill. Defer until a use case lands.
- **Schema migration: log `task_kind` on `tool_votes`** — useful for ranking analytics; deferred to a ranking-focused phase.

</deferred>

---

*Phase: 13-qa-task-enablement*
*Context gathered: 2026-05-11 via architecture discussion + codebase map*
