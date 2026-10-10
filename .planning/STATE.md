---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: Document Context Selection
status: Active
stopped_at: Completed 14-engine-hardening 14-01-PLAN.md (Task 6 pending — Railway build verify)
last_updated: "2026-10-10T20:05:00.000Z"
progress:
  total_phases: 5
  completed_phases: 1
  total_plans: 3
  completed_plans: 2
---

# Project State

## Current Position

- **Phase:** 14-engine-hardening
- **Plan:** 01 (5 of 6 tasks shipped; Task 6 — prod verify — pending Railway build of d9f5bf87)
- **Status:** Active — phase 13 (QA Task Enablement) still in flight; phase 14 inserted to track today's hardening burst.

## Progress

Phase 11 document library fully complete. Both document endpoints wired with Cache-Control headers. Requirements DOC-02 and DOC-03 satisfied.

## Decisions

- Document list endpoint returns DocumentSummary (no content) for lean catalogue responses
- Document detail endpoint returns DocumentDetail with content or 404
- Cache-Control: public, max-age=3600, stale-while-revalidate=86400 on both endpoints (CDN-appropriate)
- 404 detail message is generic "Document not found" (per spec, not interpolated with doc_id)
- Response parameter injection (not raw Response return) preserves FastAPI Pydantic serialization
- Minimal test app pattern for router integration tests to avoid psycopg2/Redis blocking imports

## Out-of-Phase Work

### 2026-05-11 — Frontend task-type restriction (two passes)
- **Pass 1 (commit `e0442485`):** Removed `'extraction'` because no server in `mcp_servers.json` declares it. Frontend `TaskType` reduced from `{summary, qa, extraction}` → `{summary, qa}`. Vercel-deployed and confirmed via SSR HTML poll.
- **Pass 2 (this commit):** User reported QA hasn't been end-to-end validated either. `TaskType` further reduced to `{summary}`. The 1-option dropdown is hidden entirely (`{#if taskTypes.length > 1}` guard) so users see a clean form instead of a degenerate select. The `requiresDocument` comparison against `'qa'` is preserved so re-enabling QA is a one-line change.
- **Scope:** Frontend only — backend `CompareRequest.task_type` Literal stays permissive.
- **Validation:** Production UI smoke test confirmed pre-fix that haystack engine no longer surfaces `NoneType is not subscriptable`. 30-iteration probe in progress (`/tmp/arena_30runs_report.md`).

### 2026-05-11 — Haystack engine None-embedding fix
- **Why:** Beta-user surfaced `TypeError: 'NoneType' object is not subscriptable` from haystack when OpenRouter returns degraded embedding payloads (200 OK with `embedding=None` instead of empty `data`).
- **What:** New `providers/embedding_validator.py` converts None payloads into the retry-marker `ValueError`; wired at both call sites in `engines/haystack_engine.py`. Unit + integration regression tests added.
- **Shipped:** Commit `071fd63e` on `develop`; `rag-pill` redeployed via `railway up --service rag-pill` (banner observed at 06:37:29 UTC).
- **Follow-up:** Symmetric fix delivered in Phase 14 (see below) — langchain, llamaindex, and chroma_baseline now have the same boundary validator.

### 2026-05-13 — Phase 14: Engine Hardening (chromadb race, leak, NoneType subscript)
- **Why:** Production screenshot 2026-05-12 showed both Tool A and Tool B failing on `chroma_baseline` with `'RustBindingsAPI' object has no attribute 'bindings'` and `KeyError: 'ephemeral'`. User then reported `'NoneType' object is not subscriptable` on `haystack` (post-retry-budget exhaustion path).
- **What:**
  - `e579b024` — chromadb 1.x EphemeralClient race: module-level singleton + asyncio.Lock to serialize first-touch.
  - `5759bd8c` — chromadb collection leak on IndexCache eviction: `_CollectionHandle` with `weakref.finalize(handle, client.delete_collection, name)`.
  - `d9f5bf87` — broadened `_is_empty_embedding_data_error` to message-substring across any exception class with `__cause__`/`__context__` chain walking; added `validate_vector_list` and wired it into langchain (pre-embed → `FAISS.from_embeddings`), llamaindex (probe `Settings.embed_model.get_text_embedding_batch`), and chroma (subclassed `OpenAIEmbeddingFunction`); bumped default `RAG_PILL_EMBEDDING_RETRIES` 2→4 (31s window).
  - `69d81719` — companion: removed stale `dispatcher.litellm` test; covered by `test_dispatch_passes_identical_task_goal_to_both`.
  - Modernization sweep: 6× `asyncio.get_event_loop()` → `asyncio.get_running_loop()` (3.14 readiness).
- **Tests:** 359 pass / 0 fail (baseline 243 + 108 + 8 new validator/retry coverage).
- **Verified (in prod):** chromadb race fix — 10-round browser-harness stress test against https://comparag.vercel.app/tool-arena returned 10/10 clean.
- **Pending (in prod):** NoneType-subscript fix — Railway building `d9f5bf87` server-side; stress test to follow.
- **Workflow change:** rag-pill now deploys via `git push` to develop, not `railway up --service rag-pill` (the CLI's chunked upload times out reliably from this machine — curl proves the endpoint is reachable in 260ms; the long-lived multipart stream is what fails). Documented in `CompaRAG/CLAUDE.md` and the corresponding memory entry.

## Deferred / Backlog

### Outil B en erreur dans l'arène (différé, 2026-10-10)

Observé en production sur https://comparag.vercel.app/tool-arena : duel QA sur
`documents/manuel_station_pompage.md` (ou son jumeau PDF `test/pdfs/`), question
« Quelle est la référence de la pièce de rechange du palier arrière de la
turbine T3 ? ». **Outil A répond correctement** (`PAL-3300-B`, avec citation de
la ligne source). **Outil B affiche « L'outil a rencontré une erreur. »**

L'identité des deux outils n'a pas été relevée — l'écran de révélation n'a pas
été consulté. C'est la première chose à faire au prochain essai.

**Écarté, avec méthode.** Le chemin de production a été rejoué hors ligne :
PDF réel → `read_uploaded_file_as_text.extract_text` (pypdf) → `EphemeralCorpus`
→ `execute_with_embedding_retry`, avec `batched_embed` et
`validate_vector_list` réels et seul le client OpenAI simulé.

| Hypothèse | Verdict |
|---|---|
| BM25 ou Hybride plantent sur ce document | ❌ les 4 combinaisons (2 moteurs × `qa_precise`/`qa_broad`) passent |
| Le registre casse le chargement backend | ❌ les 24 entrées se chargent |
| Moteur absent d'un `rag-pill` non redéployé | ❌ ce cas renvoie la *chaîne* « Unknown pill or engine », pas une erreur (`server.py`, branche `except KeyError`) |
| Le chemin réel de l'hybride (non couvert par les tests, qui injectent un faux embedder) | ❌ exercé depuis, il tient |

**Hypothèse restante, la plus probable :** un des cinq moteurs à embeddings sur
la dégradation OpenRouter déjà documentée plus haut dans ce fichier
(`No embedding data received` / `'NoneType' object is not subscriptable`), dont
le correctif `d9f5bf87` était encore marqué « Pending (in prod) ». Ce serait une
panne connue, pas une régression des moteurs ajoutés le 2026-10-10.

**Ce qu'il faut pour trancher** (nécessite un accès Railway, absent de
l'environnement de développement : ni CLI, ni jeton, et le domaine est refusé
par la politique réseau) :

1. Logs du service `rag-pill`, ligne `rag_pill_query.failed` — elle porte
   `engine_id`, `exc_type`, `exc_msg`, `doc_chars` et `duration_ms`
   (`mcp_servers/rag_pill/server.py`).
2. À défaut, refaire le duel et consulter l'écran de révélation : le nom de
   l'outil B suffit à orienter. BM25 en erreur ⇒ forcément le code local, il ne
   fait aucun appel réseau. Hybride ⇒ code local ou embeddings. Un des cinq
   anciens ⇒ la panne connue.

Par ailleurs : le message affiché à l'utilisateur est générique. Faire remonter
`exc_type` jusqu'à l'écran, au moins en mode opérateur, éviterait cet
aller-retour.

### BM25 ne concourt plus sur les résumés — décidé, à implémenter (2026-10-10)

**Constat.** En `task_type: summary`, la requête passée au retriever est la
consigne elle-même (« Résume ce document »), qui ne partage presque aucun terme
avec le corpus. Mesuré sur `documents/manuel_station_pompage.md` : BM25 ne
ramène que 1 à 3 passages sur 8 selon la formulation — il résume donc un
fragment arbitraire, pas le document.

Ce n'est pas un bug mais une conséquence du paradigme : une recherche par mots
exacts n'a rien à matcher quand la requête est une instruction.

**Décision (utilisateur, 2026-10-10) : BM25 ne concourt que sur les questions.**
Les deux autres options envisagées — lui passer le document entier en mode
résumé, ou le laisser perdre comme information sur le paradigme — sont écartées.
Motif : l'arène compare des méthodes de récupération, et faire résumer un outil
qui n'a pas de requête à chercher ne mesure rien.

**À changer :**

1. `engines/metadata.py` — entrée `bm25` : `supports=frozenset({"qa"})`.
2. `engines/bm25_engine.py` — `BM25Engine.SUPPORTS = {"qa"}`.
3. `scripts/generate_mcp_registry.py` — régénérer : `summary_default__bm25`
   disparaît, le registre passe de 24 à 23 entrées.
4. `knowledge-graph/code-ontology.yaml` — retirer la ligne
   `summary_default__bm25`, sinon `scripts/register_tool.py --check` échoue
   (le contrôle vérifie les deux sens).
5. Tests — `test_bm25_hybrid_engines.py` et `test_engine_signature.py` ne
   paramètrent BM25 que sur `qa` ; ajouter un test qui épingle la décision,
   pour qu'un futur ajout de pill `summary` ne le réintègre pas par accident.

**L'hybride garde `summary`** : sa moitié dense continue de fonctionner quand la
requête est une instruction, donc il n'a pas le même défaut. À surveiller tout
de même — en mode résumé, sa branche lexicale ne contribue presque rien à la
fusion, et son résultat devrait donc se rapprocher de celui d'un moteur dense.

### ColPali — essai en conditions réelles (différé, 2026-10-10)

Le moteur visuel est **écrit, testé et poussé** sur `feat/colpali-visual-engine`
(`407422e`, `55156ba`, `e4b56ef`, `f1757d1`). Il est tenu **hors de l'arène**
par `EngineMetadata.experimental=True` : `mcp_servers.json` est inchangé et
`generate_mcp_registry.py --check` passe. 152 tests verts.

Ce qui reste est un essai contre le vrai modèle — jamais exécuté, parce que
`huggingface.co` et `openrouter.ai` sont refusés par la politique réseau de
l'environnement de développement.

**Prérequis à réunir (côté utilisateur) :**

1. Autoriser les domaines Hugging Face dans *Network access* de l'environnement.
2. Provisionner un *Inference Endpoint* dédié sur `vidore/colpali-v1.3-hf`
   (tag `endpoints_compatible` → pas de handler maison à écrire ; facturé à
   l'heure ; l'API serverless ne convient pas, la tâche
   `visual-document-retrieval` rend plusieurs vecteurs par page).
3. Fournir l'URL de l'endpoint + un jeton HF.

**Puis :**

```bash
COLPALI_ENABLED=1 COLPALI_ENDPOINT_URL=https://<endpoint> HF_TOKEN=hf_... \
  python -m mcp_servers.rag_pill.server
```

**Ce que l'essai doit trancher :**

- La forme réelle de la réponse de l'endpoint. `HTTPColPaliBackend._as_multivector`
  accepte trois encodages plausibles et **échoue bruyamment** sinon — en
  particulier sur un vecteur unique moyenné, qui classerait quand même
  quelque chose mais sans interaction tardive, perdant le paradigme sous test
  en silence.
- La latence réelle (le smoke test de l'arène exige < 60 s).
- La qualité de récupération, qu'aucun test actuel ne couvre : la doublure de
  modèle valide la plomberie, pas le classement.

**Deux décisions restées ouvertes :**

- **Corpus de l'arène.** `mcp_servers/corpus/` est vide et `FixedCorpus` n'y lit
  que `*.md` — le mode corpus est inerte pour les six moteurs, pas seulement
  pour ColPali. Quatre PDF de test existent dans `test/pdfs/` ; reste à décider
  ce qui devient le corpus de production. `VisualCorpus` sert aussi les moteurs
  texte, donc un seul corpus PDF suffit pour tous.
- **Répondre depuis un scan.** ColPali trouve la page, mais le moteur passe
  ensuite le *texte* de la page au LLM — et un scan n'en a pas. Sortie à
  choisir : envoyer l'image au LLM (multimodal, parité préservée) ou OCR de
  repli. Épinglé par
  `test_colpali_on_test_pdfs.py::test_retrieving_a_scanned_page_hands_the_llm_nothing`.

Détail complet : `mcp_servers/rag_pill/COLPALI.md`.

## Last Session

- **Stopped at:** Completed 11-document-library 11-02-PLAN.md (with Cache-Control and test_documents_endpoints.py)
- **Timestamp:** 2026-04-20T11:45:00Z

## Performance Metrics

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 11-document-library | 02 | 15min | 2 | 3 |
