---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: Document Context Selection
status: Active
stopped_at: Completed 14-engine-hardening 14-01-PLAN.md (Task 6 pending — Railway build verify)
last_updated: "2026-10-11T10:00:00.000Z"
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

### Le rerank est annoncé mais n'existe pas (2026-10-11)

**Les sept entrées `qa_broad` de `mcp_servers.json` affichent « top_k=8,
rerank » en production, et aucun moteur ne reclasse quoi que ce soit.**
Vérifié le 2026-10-11 : zéro occurrence de `pill.rerank` dans
`mcp_servers/rag_pill/engines/`.

Le champ existe pourtant partout ailleurs : `QAPill.rerank` dans
`schemas.py:42`, `rerank: true` dans `pills/qa_broad.yaml`, et la page
d'explication de l'arène cite le reranker parmi les choix d'architecture
comparés (`frontend/locales/messages/*.json`, clé `toolArena…desc`).

Ce n'est donc pas une fonctionnalité manquante mais une **information fausse
affichée aux votants** : ils comparent deux outils en croyant qu'un
reclassement a lieu, alors qu'aucun n'en fait. C'est le seul point de ce
backlog qui soit incorrect en production plutôt qu'incomplet.

**Deux sorties, à trancher :**

1. **L'implémenter.** C'est le gain le mieux documenté du RAG — une seconde
   passe qui retrie les candidats avec un modèle plus fin que la similarité
   de première passe. Recommandé.
2. **Cesser de l'annoncer.** Retirer `rerank` du schéma, des pills et des
   libellés. Honnête et immédiat, mais on perd un axe de comparaison que
   l'arène prétend mesurer.

**Si on l'implémente — l'architecture compte.** Le rerank est un paradigme
*transverse*, pas un trait de moteur : il s'applique **après** le `retrieve()`
de n'importe quel moteur, sur les `RetrievedSpan` déjà normalisés par
`EngineResult`. Il s'écrit donc **une fois** dans `providers/`, branché autour
de `execute_with_spans()`, et profite aux sept moteurs d'un coup — pas sept
implémentations qui réintroduiraient la variable qu'on cherche à isoler.

Concrètement : récupérer un vivier plus large que `top_k` (le moteur a déjà
`CANDIDATE_POOL_MULTIPLIER` côté hybride), retrier, tronquer à `top_k`. Un
cross-encoder hébergé (Cohere Rerank) ou local (`bge-reranker`) ; le premier
ajoute un coût par requête, le second du poids à l'image — même arbitrage que
ColPali, mais sur des modèles bien plus petits, donc à chiffrer avant de
choisir.

**Mesurable immédiatement** : le benchmark existe maintenant
(`mcp_servers/corpus/evaluation/queries.yaml`). Recall@K avant et après
rerank, sur les six questions, dit si le gain est réel sur ce corpus plutôt
que supposé — y compris sur les deux questions à plusieurs sauts, où BM25
plafonne aujourd'hui à 0,50 en Recall@3.

### Formulaire de l'arène — test utilisateur / UI-UX à faire (2026-10-10)

Deux ajouts au même formulaire, à vérifier ensemble :

- **Sélecteur de documents** — `b50d2a5` (client + 10 tests) et `4ce92c0`
  (branchement dans `ToolArenaForm.svelte`).
- **Mode benchmark** — `b3e7ee2` : sélecteur de mode, liste des six questions
  de référence, et `GET /tool-arena/questions` côté backend.

CI verte sur les deux, `vite build` exit 0.

**Jamais vu tourner.** Aucune vérification visuelle ni d'interaction réelle n'a
été faite — l'environnement de développement ne peut pas rendre la page
(le plugin paraglide se télécharge depuis un CDN refusé par la politique
réseau, donc le module de traduction généré localement ne contient aucune clé
`toolArena`). Ce qui est couvert : la logique du client, en pur TS, hors DOM.

**À vérifier à l'écran :**

1. Les trois clés `toolArena.form.library*` s'affichent bien traduites, dans les
   5 langues. C'est le point le plus incertain : localement elles ne résolvent
   pas, et seul un build avec réseau le dira.
2. La liste apparaît avec les 4 documents et le manuel est sélectionnable.
3. Choisir un document remplit bien le formulaire et le bouton se débloque.
4. **Exclusion mutuelle dans les deux sens** : téléverser un fichier après avoir
   choisi dans la liste doit vider la sélection, et inversement. C'est la partie
   la plus facile à casser.
5. Changement rapide de sélection : le garde anti-réponse-périmée (`fileToken`)
   doit empêcher qu'un chargement lent écrase un choix plus récent.
6. Rendu mobile — le duel de ce soir a été joué depuis un téléphone.
7. Placement : la liste est sous le bouton de téléversement. À voir si c'est le
   bon ordre, ou si un document prêt à l'emploi devrait venir en premier pour un
   nouvel arrivant.

**À vérifier pour le mode benchmark :**

8. Le menu « Sur quoi comparer » apparaît, et bascule bien entre les deux modes.
9. En mode benchmark, le formulaire se réduit comme prévu : plus de dépôt de
   document, plus de zone de question, plus de suggestions, plus de champ
   objectif — mais **le bouton Comparer reste visible**. Il vit dans la même
   grille que le champ objectif, c'est le point le plus fragile de la mise en
   page.
10. Les six questions sont lisibles dans la liste. Certaines sont longues : à
    voir si elles tiennent sur mobile sans être tronquées.
11. Le duel part et revient avec deux réponses. C'est le premier passage réel en
    `haystack: "benchmark"` — le chemin backend est testé, le bout-en-bout non.
12. Après le vote : les scores automatiques sont-ils visibles quelque part ?
    Le backend les enregistre (`judgement_a` / `judgement_b`), mais **rien ne
    les affiche à l'écran**. C'est probablement le prochain morceau : un
    benchmark dont personne ne voit le résultat ne sert à rien.
13. Question de fond plutôt que d'affichage : le mode benchmark a-t-il sa place
    dans l'arène grand public, ou devrait-il vivre dans une page séparée ? Un
    visiteur venu voter sur son propre document n'a sans doute rien à faire
    d'un corpus de maintenance de station de pompage.

**Ajout du 2026-10-25 — aperçu du document et exemple fourni avec lui.**
Un document prêt à l'emploi n'était qu'un titre dans une liste : on le
choisissait, on recevait deux réponses anonymes, et on n'avait aucun moyen de
dire laquelle était juste puisqu'on n'avait jamais lu le document. Deux
corrections, même formulaire :

- **Aperçu** — le début du document (700 caractères, dépliable jusqu'à 20 000)
  s'affiche sous le sélecteur, avec sa description et son nombre de caractères.
  Vaut aussi pour un téléversement : c'est la preuve que l'extraction d'un
  `.pdf` ou d'un `.docx` a produit du texte lisible.
- **Exemple livré avec le document** — `documents_index.json` porte désormais
  `suggested_question` / `expected_answer` par entrée, servis par les deux
  endpoints. Choisir un document bascule le formulaire en Question/Réponse et
  pré-remplit la question et la réponse attendue, sauf si l'utilisateur a déjà
  tapé sa propre question : dans ce cas l'exemple reste proposé derrière un
  bouton. La paire du manuel de pompage est volontairement celle qui ne partage
  aucun mot avec le texte (lubrifier/graissage, roulements/paliers) — le premier
  duel montre donc d'emblée l'écart entre recherche lexicale et recherche par
  sens.

**À vérifier à l'écran, en plus de la liste ci-dessus :** que l'aperçu ne
pousse pas la zone de question hors écran sur mobile, que le dépliage d'un
document long reste fluide, et que la bascule automatique vers
Question/Réponse ne surprenne pas quelqu'un venu faire un résumé. Mêmes
limites qu'au-dessus : jamais vu tourner ici, pour la même raison (CDN
paraglide refusé par la politique réseau).

**Contexte qui rend ce test nécessaire :** la CI ne construit jamais le
frontend. `build-deploy-dev.yml` et `deploy-prd.yml` se déclenchent sur les
branches `dev` et `prd`, qui n'existent pas dans ce fork — ce sont des restes du
dépôt ComparIA d'origine et ils n'ont jamais tourné. Seule la suite de
régression (Python) est active. Une régression frontend passerait donc
inaperçue jusqu'au build Vercel. Deux chantiers séparés en découlent : ajouter
le build frontend à la régression, et supprimer les deux workflows morts.

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

### ColPali — PROJET ANNULÉ (2026-10-11)

**Décision utilisateur : l'intégration de ColPali est abandonnée. Motif : coût.**

Le moteur était écrit, testé et fusionné dans `develop`, mais tenu hors de
l'arène par `EngineMetadata.experimental=True`. Il n'a jamais tourné contre
de vrais poids.

**Les chiffres qui ont tranché** (tarifs relevés le 2026-10-11, à reconsidérer
s'ils bougent) :

| Chemin | Coût |
|---|---|
| Inference Endpoint Hugging Face, T4 | 0,50 $/h — ~75 $/mois en usage sporadique, ~360 $/mois en continu |
| Inference Endpoint, L4 | 0,70–0,80 $/h |
| Auto-hébergement Railway, CPU, `colSmol-256M` | ~30 à 50 $/mois en continu |

Pas d'API serverless gratuite : la tâche `visual-document-retrieval` renvoie
plusieurs vecteurs par page, ce qu'aucun pipeline serverless n'expose. Un
endpoint dédié est donc le seul chemin hébergé, et il se facture à l'heure.

Deux pièges relevés au passage, qui ont pesé dans la balance : le
scale-to-zero coupe la facture mais renvoie 502/503 au réveil **sans file
d'attente**, alors que le smoke test de l'arène exige une réponse en moins de
60 s ; et l'option CPU impose `colSmol-256M`, le plus petit de la famille —
s'il perdait ses duels, on ne saurait pas si c'est le paradigme visuel ou le
modèle, soit 40 $/mois pour une mesure ambiguë.

**Code supprimé le 2026-10-11**, sur décision utilisateur, dans la foulée de
l'annulation. Retirés : `engines/colpali_engine.py`,
`engines/colpali_backend.py`, `corpus/visual.py`, `requirements-colpali.txt`,
`COLPALI.md` et cinq fichiers de tests — environ 1 570 lignes, 40 tests. La
suite `rag_pill` passe de 202 à 162 tests.

Le mécanisme `EngineMetadata.experimental` est parti avec, ainsi que sa garde
dans `generate_mcp_registry.py` : plus aucun moteur ne s'en servait, et il
n'était couvert par aucun test. À réintroduire si un futur moteur a besoin
d'être présent sans concourir.

Motif de la suppression plutôt que de la mise en veille : du code que personne
n'exécute pourrit en silence — c'était déjà arrivé ici, un test listant quatre
PDF alors qu'il y en avait cinq, invisible en CI parce que le module entier y
était ignoré faute de PyMuPDF.

Tout reste récupérable dans l'historique git (`f1df78b` et ses parents) si le
dossier est rouvert.

**Conservés**, pour des raisons indépendantes de ColPali : `test/pdfs/` et son
générateur `scripts/build_test_pdfs.py`. Le manuel sert aux essais d'interface
sur BM25 ; le rapport scanné documente ce que l'extraction de texte perd — zéro
caractère sur un document lisible à l'œil, ce qui reste une limite mesurée du
paradigme en vigueur dans l'arène. Leur documentation (`test/README.md`) a été
recadrée en conséquence.

**Ce qui rouvrirait le dossier :** un GPU déjà payé par ailleurs, une baisse
des tarifs horaires, ou un corpus client où l'information vit réellement dans
l'image (PDF scannés, tableaux complexes) — auquel cas la question « est-ce que
le paradigme gagne ? » redeviendrait rentable à poser, pour moins d'un dollar
d'essai ponctuel.

## Last Session

- **Stopped at:** Completed 11-document-library 11-02-PLAN.md (with Cache-Control and test_documents_endpoints.py)
- **Timestamp:** 2026-04-20T11:45:00Z

## Performance Metrics

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 11-document-library | 02 | 15min | 2 | 3 |
