# Legacy standalone MCP servers

Ces serveurs MCP (`langchain_rag` sur port 8010, `llamaindex_rag` sur port 8011)
ont été remplacés par `rag_pill` (port 8012) qui wrappe les mêmes frameworks
comme moteurs configurables — un seul serveur, cinq moteurs (LangChain,
LlamaIndex, Haystack, Txtai, Chroma).

Ils restent ici en lecture seule pour :

- pouvoir comparer A/B sur Railway si un bug est suspecté dans rag_pill ;
- servir de référence pour le wrapping d'un framework existant comme
  moteur de `rag_pill/engines/` ;
- accélérer un éventuel retour en arrière.

À supprimer définitivement quand `rag_pill` aura prouvé sa stabilité en
production sur les 5 moteurs (suivi : knowledge-graph/code-ontology.yaml,
entité RAGTool > currently_known_instances).

**Ne pas démarrer ces serveurs en production sans coordination.** Ils ne
sont plus référencés dans `mcp_servers.json` ; les y rajouter casserait la
disposition "un RAGTool = une pilule rag_pill".
