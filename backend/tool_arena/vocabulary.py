"""
BUT : être le glossaire de référence du Tool Arena pour quelqu'un qui
raisonne en termes d'ontologie orientée buts. Quand un nom technique apparaît
dans le code, regarder ici pour savoir à quel concept du domaine il
correspond, et inversement.

Ce module est de la documentation. Il n'a aucun effet à l'exécution — les
constantes ne sont pas utilisées par le code (encore). Elles servent à :

  - faciliter la relecture du code par l'auteur non-développeur du projet ;
  - servir de table d'équivalence pendant Phase D (renames de fichiers
    + coordination frontend) et Phase E (migrations DB) ;
  - être grep-able : `rg "CANONICAL_QUESTION" backend/` pointe vers ce fichier.

Source de vérité : `knowledge-graph/code-ontology.yaml`.
Quand l'ontologie change, mettre à jour ce fichier ET la table.
"""
from __future__ import annotations


# Concept du domaine -> liste des noms techniques utilisés aujourd'hui.
#
# Le premier nom de chaque liste est le nom canonique vers lequel on tend.
# Les noms suivants sont les noms techniques que le code utilise encore et
# qu'on veut faire disparaître (rename en Phase D / Phase E).
CANONICAL_VOCABULARY: dict[str, list[str]] = {
    # La question que l'utilisateur pose. La fusion de `task` (instruction)
    # et `goal` (critère de succès) en un seul champ `question` sera faite
    # en Phase D, conjointement avec une mise à jour du frontend.
    "question": ["question", "task", "goal", "query", "prompt"],

    # La réponse d'un RAGTool. Plusieurs étapes nommées explicitement pour
    # qu'on sache toujours de quelle version on parle.
    "answer": [
        "answer",
        "result",
        "output",
        "raw_result",
        "mediated_result",
        "sanitized",
    ],
    "answer_as_returned_by_tool": ["answer_as_returned_by_tool", "raw_result"],
    "answer_after_mediation": ["answer_after_mediation", "mediated_result"],
    "answer_with_identity_hidden": ["answer_with_identity_hidden", "sanitized"],

    # L'outil RAG (un serveur MCP distant). Garder `mcp_*` uniquement où
    # l'on parle littéralement le protocole MCP (mcp_session, mcp_call).
    "rag_tool": ["rag_tool", "MCPServer", "provider", "client", "tool"],

    # L'identifiant d'une comparaison. `session_id` est trop générique et
    # collisionne avec FastAPI/Redis ; à supprimer en Phase E (migration DB
    # de la colonne session_hash en comparison_id).
    "comparison_id": ["comparison_id", "session_hash", "session_id"],

    # Préservation de l'aveuglement.
    "hide": ["hide", "sanitize", "strip_identity"],
    "reveal": ["reveal"],

    # Score automatique d'une réponse.
    "judge_verdict": ["judge_verdict", "evaluation", "score", "judgement"],

    # Disponibilité d'un RAGTool.
    "ready": ["ready", "available", "up", "healthy"],
}


# Inverse : nom technique courant -> concept canonique du domaine.
# Utile pour grep : si vous voyez `mediated_result` dans le code et vous
# vous demandez de quel concept il s'agit, regardez ici.
TECHNICAL_TO_CANONICAL: dict[str, str] = {
    technical: canonical
    for canonical, technical_names in CANONICAL_VOCABULARY.items()
    for technical in technical_names
    if technical != canonical
}
