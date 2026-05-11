# Phase 13: QA Task Enablement (Needle-in-Haystack Retrieval Arena) — Context

**Gathered:** 2026-05-11
**Status:** Ready for planning
**Source:** Architecture grilling 2026-05-11 (re-framed mid-discussion from "QA over uploaded doc" to "needle-in-haystack retrieval competition")
**Supersedes:** v1 of this CONTEXT.md (committed in `59764931` then revised — git history preserves the original assumptions)

<domain>
## Phase Boundary

Enable the **Q&A task type** in the Tool Arena as a **needle-in-haystack retrieval competition**: multiple `(pill × engine)` combinations compete on the *same* query against the *same* haystack, and the arena measures *which combination's retrieval surfaced the right passage*. The mediator's job stays neutral (answer from retrieved context); the variant is the retrieval recipe (engine choice, `top_k`, `rerank`, chunk strategy).

**Two modes coexist:**
- **Benchmark mode** — fixed corpus + curated `queries.yaml` with ground truth. Produces automated scores (Recall@K, MRR, NDCG@K). Feeds the leaderboard.
- **Sandbox mode** — user-uploaded document, freeform query. No ground truth. Retrieved spans are still shown (UX win), but only the user vote ranks it.

The phase also delivers the **progress-UX requirement** the user surfaced explicitly: ingestion of a corpus by 5 engines is not instant. The UI must show work-in-progress per engine so the user understands the wait.

**Out of scope (deferred):**
- Evaluation packs (multiple curated corpora) — start with one.
- LLM-as-judge — deferred until ground-truth scoring proves insufficient.
- `mcp_servers.json` codegen from `list_contestants()` — cleanup, defer.
- Hybrid (lexical + dense) retrieval pills — pure dense for v1.
- Per-task `TaskMediator` polymorphism — the needle-in-haystack framing dissolves the second adapter. One shared mediator (current `strategies/qa.py`) is enough until a non-retrieval task arrives.

</domain>

<decisions>
## Implementation Decisions

### Comparable retrieval unit
- **`RetrievedSpan`** = `{source_doc_id, char_start, char_end, text, score, rank}`. Engine-agnostic projection of every native chunk format (Chroma `(id, doc, distance)`, Haystack `Document`, LlamaIndex `NodeWithScore`, txtai `(row, score)`, LangChain `Document`).
- **Locating spans in the source** = post-hoc via `source.find(chunk.text)` at engine return time. Failure to locate → drop the span + log + add to `normalized_fields`. **Not** preprocessing the corpus splits — engines keep their pill-specific chunking.
- **Recall comparison** = interval overlap, not id equality. A retrieved span counts as a hit if its `[char_start, char_end)` overlaps any `expected_span` in the eval query.

### Haystack corpus seam
- New module `mcp_servers/rag_pill/corpus/` with `HaystackCorpus` Protocol.
- Two adapters earn the seam:
  - **`FixedCorpus(root=mcp_servers/corpus/)`** — reads `*.md` files, exposes `list_evaluation_queries()`, `has_ground_truth=True`. Replaces all 5 engines' `CORPUS_DIR = ...` duplication.
  - **`EphemeralCorpus(documents=[CorpusDocument(id="upload-{sha256}", text=upload)])`** — `has_ground_truth=False`, empty queries list. Used when the user uploads in sandbox mode.
- Engines receive a `HaystackCorpus` in their constructor (or per-call). They no longer reach into `CORPUS_DIR` directly.

### Ground truth contract
- **`corpus/evaluation/queries.yaml`** — YAML list of `EvaluationQuery` entries.
- `EvaluationQuery` = `{id, query_text, goal_text, expected_spans: list[ExpectedSpan], notes?: str}`.
- `ExpectedSpan` = `{source_doc_id, char_start, char_end}`. A query can have multiple expected spans (the answer lives in multiple passages).
- Pinned to a corpus *version hash* (sha256 over sorted `*.md` contents) so re-chunking the corpus invalidates stale eval queries. Mismatched hash → corpus startup raises.

### Request shape
- `CompareRequest` gets a discriminator `haystack: Literal["benchmark", "sandbox"] = "sandbox"` (defaults sandbox for back-compat).
- Benchmark mode: `evaluation_query_id: str` required, `document_content` ignored.
- Sandbox mode: `document_content: str` required (non-empty), `evaluation_query_id` ignored.
- The router's `model_validator(mode="after")` enforces the XOR.

### Judging seam
- New `RetrievalJudge` Protocol in `backend/tool_arena/judge/`.
- Single adapter for v1: **`GroundTruthJudge`** — given `RetrievedSpan[]` + `ExpectedSpan[]`, computes:
  - `recall_at_k` for `k in {1, 3, 5, 10}` (configurable in `ontokit.json`-style config)
  - `mrr` (mean reciprocal rank of first hit)
  - `ndcg_at_k` for `k=10`
  - `contains_gold: bool` (any span overlapped any expected span)
- Score is computed only when `corpus.has_ground_truth and request.haystack == "benchmark"`. Sandbox mode skips the judge.
- Judgement scores stored as a new JSON column on `tool_votes` (additive migration; existing rows have `null`).

### Progress streaming
- `POST /tool-arena/compare` becomes a **Server-Sent Events** endpoint, mirroring the pattern in `backend/arena/streaming.py`.
- Per-engine event types (all carry `side: "a" | "b"`):
  - `ingest_start { side, engine_id, pill_id }`
  - `ingest_progress { side, processed_docs, total_docs }` (emitted at most every 500ms to avoid event spam)
  - `ingest_done { side, took_ms }`
  - `retrieval_start { side }`
  - `retrieval_done { side, span_count, took_ms }`
  - `mediation_start { side }`
  - `mediation_done { side, took_ms }`
  - `complete { session_hash, result_a, result_b, error_a, error_b }` — terminal event, same shape as today's `CompareResponse`.
- The current synchronous `CompareResponse` JSON shape is kept for back-compat: clients that don't accept SSE get a single JSON blob (negotiate via `Accept` header).
- Cache hits (engine has already indexed this `(pill, corpus_hash)`) emit `ingest_done` immediately with `took_ms=0` and a `cache_hit: true` field — the UI shows "✓ cached" instead of a progress bar.

### Engines refactor
- Each engine's `execute()` signature changes from `(pill, task, goal, document_content) -> str` to:
  ```python
  async def execute(
      self,
      pill: Pill,
      query: RetrievalQuery,                 # {task, goal, evaluation_query_id?}
      corpus: HaystackCorpus,
      progress: ProgressEmitter,             # callback(event_dict) — no-op in tests
  ) -> EngineResult                          # {answer, retrieved_spans, retrieval_latency_ms, generation_latency_ms}
  ```
- `EngineResult` is the new typed return. Normalizer maps it onto `NormalizedEnvelope` extended with `retrieved_spans`.

### Back-compat
- Sandbox mode + summary task = exactly today's behaviour. No UX regression for existing flows.
- The old `document_content` field stays on `CompareRequest` — used by sandbox + summary.
- The current `mediated_result` string field stays on `MCPToolCall` — additive only.

### Claude's Discretion
- Exact SSE chunking interval (between 250ms and 1s).
- Whether ingest-progress fires per document or per chunk (likely per document — chunks are too noisy).
- File format for v1 eval set (YAML chosen for legibility; could be JSON if YAML parser becomes a build pain in the rag-pill container).
- Whether NDCG uses logarithmic or linear gain (default: standard logarithmic).

</decisions>

<canonical_refs>
## Canonical References

### Codebase map
- `.planning/codebase/ARCHITECTURE.md` — 3-router pattern, dispatcher / client / normalizer pipeline.
- `.planning/codebase/STRUCTURE.md` — directory layout.
- `.planning/codebase/CONCERNS.md` — dispatcher pool=2 footgun (`backend/tool_arena/dispatcher.py:133`), rag-pill manual deploy, embedding-validator asymmetry.

### Backend
- `backend/tool_arena/router.py:229-237` — current `CompareRequest`.
- `backend/tool_arena/dispatcher.py:60-145` — dispatch + task_type grouping.
- `backend/tool_arena/normalizer.py` — `NormalizedEnvelope` shape (extends with `retrieved_spans`).
- `backend/tool_arena/models.py:37-62` — `MCPToolCall`.
- `backend/tool_arena/persistence.py` — Postgres + Redis writes (judge scores migration).
- **`backend/arena/streaming.py`** — reference SSE pattern for the LLM arena. Mirror this in tool_arena.

### MCP rag-pill server (the deepest changes land here)
- `mcp_servers/rag_pill/engines/base.py` — `RAGEngine` Protocol. Signature changes.
- `mcp_servers/rag_pill/engines/{chroma_baseline,haystack,langchain,llamaindex,txtai}_engine.py` — all 5 refactor to return `EngineResult` and accept `HaystackCorpus + ProgressEmitter`.
- `mcp_servers/rag_pill/registry.py` — `list_contestants(task_type)` still returns `(pill_id, engine_id)` pairs; the pill loader now validates against the (also-new) corpus version hash.
- `mcp_servers/rag_pill/schemas.py` — `QAPill` already exists with `top_k`, `rerank`, `cite_sources`. No changes.
- `mcp_servers/rag_pill/strategies/qa.py` — current QA prompt is fine. No changes (the mediator stays neutral).
- `mcp_servers/rag_pill/server.py` — MCP envelope grows `retrieved_spans` and progress events.

### Pills
- `mcp_servers/rag_pill/pills/qa_precise.yaml` — existing, keep.
- **NEW** `mcp_servers/rag_pill/pills/qa_broad.yaml` — from plan 13-01 (kept from v1).

### Frontend
- `frontend/src/routes/tool-arena/+page.svelte:74` — request body assembly; will toggle on `haystack` mode.
- `frontend/src/routes/tool-arena/components/ToolArenaForm.svelte:27-70` — `TaskType` literal, taskTypes array; QA gets unhidden.
- **NEW** components: a benchmark query picker, a per-engine progress card, a retrieval-spans viewer.

### ADRs
- `docs/adr/0001-oauth-rekey-via-admin-endpoint.md` — irrelevant here.

### Deployment caveats
- `rag-pill` Railway service is **manual-deploy only**: `railway up --service rag-pill`. Called out in each plan's `<verify>` block as needed.
- `make mcp-registry` may need re-run after pill additions; `make mcp-registry-check` gates CI.

### Prior commits relevant to this phase
- `df3b5a6a` — QA task-type field kept visible even with 1 option (already unblocks the picker showing one option).
- `de5b0372` — QA hidden until end-to-end validated (this phase clears the gate).
- `071fd63e` — haystack engine None-embedding retry-safety (referenced by 13-02 corpus rebuild paths).
- `e0442485` — extraction removed; informs that the `TaskKind`-style cleanup is a *later* phase.
- `59764931` — Phase 13 v1 plans (superseded by this CONTEXT but kept in git history).

</canonical_refs>

<specifics>
## Specific Ideas

- **Initial benchmark corpus**: 10–20 curated `.md` files in `mcp_servers/corpus/` (already partially populated per existing engine fallbacks). Add `corpus/evaluation/queries.yaml` with ~15 needle queries pointing at known passages.
- **Initial query example**:
  ```yaml
  - id: q01_capital_france
    query_text: "Quelle est la capitale de la France ?"
    goal_text: "Réponse précise avec citation du passage source."
    expected_spans:
      - { source_doc_id: "geography_fr.md", char_start: 1245, char_end: 1389 }
    notes: "Easy needle — one well-formed paragraph contains the canonical answer."
  ```
- **Pills for v1**: `qa_precise.yaml` (top_k=3) and `qa_broad.yaml` (top_k=8, rerank=true). Engines × pills = 5 × 2 = 10 contestants for QA.
- **Progress UI mockup** (per side):
  ```
  ┌─ Side A: chroma_baseline + qa_precise ─┐
  │ ✓ Ingested 18/18 docs (1.2s)            │
  │ ⏳ Retrieving... (top_k=3)               │
  │ ⏳ Mediating answer...                    │
  └──────────────────────────────────────────┘
  ```
- **Judging output**:
  ```json
  {
    "side": "a",
    "recall_at_3": 1.0,
    "mrr": 1.0,
    "ndcg_at_10": 0.92,
    "contains_gold": true,
    "hits": [{"rank": 0, "expected_span_idx": 0}]
  }
  ```
- **Span viewer**: clicking a retrieved span in the UI scrolls + highlights the source file in a side pane. (Defer to a polish phase if 13-07 runs long.)

</specifics>

<deferred>
## Deferred Ideas

- **LLM-as-judge** (advisory scoring for sandbox mode) — Phase 14+.
- **Evaluation packs** (multiple curated corpora) — Phase 14+ once a second domain appears.
- **TaskKind module** (architecture candidate #1 from the first review) — still valuable, but not load-bearing for needle-in-haystack. Re-open when a third task type joins (extraction comes back, classification arrives).
- **mcp_servers.json codegen from list_contestants()** — cleanup, Phase 14+.
- **Hybrid retrieval pills** (BM25 + dense) — Phase 15+.
- **Gold-truth highlight UI** (full mode (d) from the grilling) — only revisit if benchmark adoption is too low.
- **Per-engine retrieval-config knob exposure** (e.g. let `qa_precise` configure HNSW M, ef_search for haystack engine) — pill schema currently abstracts this away; revisit if engine-internal tuning becomes a competition axis.

</deferred>

---

*Phase: 13-qa-task-enablement*
*Re-framed: 2026-05-11 via grill-me skill on architecture candidate #1*
