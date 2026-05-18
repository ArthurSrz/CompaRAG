# Ajouter un nouveau RAGTool à l'arène

Guide pas-à-pas pour intégrer un nouvel outil RAG (LightRAG, R2R, Vectara,
PaperQA, etc. — cf. la liste de candidats dans le plan de simplification).

## Vue d'ensemble

Un RAGTool est, du point de vue de l'arène, un serveur MCP qui répond à
`rag_query(task, goal, document_content) -> str`. Toute la connaissance du
domaine est dans `knowledge-graph/code-ontology.yaml` — chaque ajout doit s'y
refléter.

## Procédure (5 étapes, ~30 minutes)

### 1. Copier le template

```bash
cp -r mcp_servers/_template_new_tool mcp_servers/<slug>
cd mcp_servers/<slug>
```

Choisir un `<slug>` court, snake_case, unique dans l'arène.

### 2. Remplir `tool.manifest.yaml`

C'est le contrat de l'outil. Champs critiques :

- `tool_id` : remplace `TEMPLATE_REPLACE_ME` par le `<slug>`.
- `display_name` : ce que voit l'utilisateur après le BlindReveal.
- `goal` : une phrase qui dit ce que l'outil sait faire mieux que les autres.
- `endpoint` : URL Railway en prod, `http://localhost:<port>/mcp` en dev.
- `auth` : `none` / `api_key` / `oauth2`. Pour OAuth, suivre `scripts/auth_setup.py`.
- `task_type` : `summary` | `qa` | `extraction`. Le dispatcher ne met en
  compétition que des outils du même `task_type` (fairness invariant).
- `sanitize.extra_terms` : termes à effacer dans la réponse pour préserver
  l'aveuglement du vote.

### 3. Implémenter `server.py`

Remplacer le `raise NotImplementedError` de la fonction `rag_query` par la
vraie logique du moteur. Référence : `mcp_servers/rag_pill/server.py`.

Contraintes critiques :

- **Pas de troncation** : utiliser un modèle qui n'est pas Cloudflare-only
  (cf. `scripts/check_openrouter_providers.py`).
- **`max_tokens` honoré** : si possible 4096+ pour ne pas que le moteur
  s'auto-coupe.
- **Embeddings non-None** : si le moteur passe par OpenRouter, valider que
  le provider ne renvoie pas de payload vide (cf. test_haystack_none_embedding_regression.py).

### 4. Enregistrer dans l'arène

```bash
python scripts/register_tool.py <slug>
```

Le script met à jour automatiquement :

- `mcp_servers.external.json` (source de vérité pour les outils standalone
  — c'est ce fichier qu'éditent les commits, jamais `mcp_servers.json`).
- `mcp_servers.json` (régénéré par `scripts/generate_mcp_registry.py` à
  partir de `rag_pill/pills/` + `mcp_servers.external.json` ; les deux
  doivent être commités ensemble).
- `knowledge-graph/code-ontology.yaml` : une ligne insérée dans
  `rag_tool.metadata.currently_known_instances` (édition texte, donc
  commentaires et formatage préservés).

NB : les pills de `rag_pill` (LangChain, LlamaIndex, etc.) ne passent
**pas** par ce script — elles sont matérialisées à partir de
`mcp_servers/rag_pill/pills/*.yaml` par le générateur. Ce script ne sert
qu'aux outils standalone (un dossier sous `mcp_servers/`).

### 5. Vérifier

```bash
# Suite de régression complète
pytest backend/ mcp_servers/rag_pill/tests

# Provider OpenRouter (détecte Cloudflare-only)
python scripts/check_openrouter_providers.py

# Smoke test contre le stack local
make dev  # dans un autre terminal
python scripts/smoke_test.py

# Cohérence ontology ↔ mcp_servers.json
python scripts/register_tool.py --check
```

Tous les checks doivent passer avant de pousser une PR.

## Liste de candidats à scouter

Cf. le plan de simplification — `knowledge-graph/code-ontology.yaml` ne liste
que les RAGTool déjà intégrés. Candidats actuels (mai 2026) :

| Candidat | Type | Pourquoi |
|---|---|---|
| LightRAG (HKU) | Graph-RAG | Knowledge graph + recherche hybride, EMNLP 2025 |
| R2R (SciPhi) | Agentique | API REST, multi-step reasoning |
| Vectara MCP | Commercial MCP-native | Pas de wrapping, juste enregistrer l'URL |
| Pinecone MCP | Commercial MCP-native | Idem Vectara, basé sur Pinecone |
| PaperQA2 | Scientifique | Citations natives, idéal littérature scientifique |
| Verba (Weaviate) | Out-of-the-box | Bonne baseline grand public |
| RAGFlow | Production | Concurrent direct de LangChain/LlamaIndex |
| Cohere RAG (command-r) | Provider direct | Modèle entraîné pour le RAG avec citations |

## Critère d'ajout

Un nouveau RAGTool ne rejoint l'arène que si :

1. Il passe le smoke test (`/compare` répond en < 60s, réponse > 200 chars).
2. Il passe le check OpenRouter si il en dépend (pas de Cloudflare exclusif).
3. Une entrée `RAGTool[<slug>]` apparaît dans `code-ontology.yaml`.
4. Son nom apparaît dans la liste révélée après vote (automatique via le manifeste).
