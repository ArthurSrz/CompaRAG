# ColPali dans l'arène — état, limites, mise en service

ColPali est le premier moteur de CompaRAG dont le signal de récupération
n'est pas du texte. Il est **implémenté et testé, mais volontairement hors
de l'arène** (`EngineMetadata.experimental=True`) tant que les deux
prérequis ci-dessous ne sont pas remplis.

## Le paradigme, en une phrase

Au lieu de découper le texte en chunks et d'embedder chaque chunk, ColPali
**rend chaque page en image** et l'encode avec un modèle vision-langage,
en gardant *tous* les vecteurs de patchs. La requête garde elle aussi tous
ses vecteurs de tokens, et le score est un **MaxSim** : chaque token de la
requête choisit son meilleur patch de page, et on somme ces maxima.

Conséquence pratique : rien n'est parsé avant l'indexation. Les tableaux,
les schémas, les colonnes, les PDF scannés survivent — là où les cinq
moteurs texte dépendent entièrement de ce que `pypdf` a bien voulu extraire.

## Ce qui est fait

| Composant | Fichier | Testé |
|---|---|---|
| Corpus de pages (image + texte + intervalle de caractères) | `corpus/visual.py` | `tests/test_visual_corpus.py` |
| Scoreur MaxSim | `engines/colpali_backend.py` | `tests/test_colpali_maxsim.py` |
| Backend modèle (`colpali-engine` + torch), derrière un Protocol | `engines/colpali_backend.py` | — (poids réels requis) |
| Moteur RAGEngine | `engines/colpali_engine.py` | `tests/test_colpali_engine.py` |
| Métadonnées + garde `experimental` du générateur | `engines/metadata.py`, `scripts/generate_mcp_registry.py` | `tests/test_generator.py` |

### Deux décisions de conception à connaître

**1. ColPali est un *retriever*, pas un générateur.** Il classe les pages
sur les pixels, puis passe le *texte* des pages retenues au même
`LLMProvider` que tous les autres moteurs. L'invariant de l'arène — un seul
LLM pour tous les concurrents, donc un vote mesure la récupération — reste
intact. Un vote contre ColPali est un vote sur la récupération visuelle,
pas sur la prose d'un autre modèle.

**2. Il ignore `pill.embedder`.** C'est la seule entorse à la parité, et
c'est l'objet même de la comparaison : l'encodeur visuel *est* le
paradigme. C'est dit dans le `display_label` pour que le BlindReveal ne
trompe personne.

`chunk_size` / `chunk_overlap` sont également inutilisés : **la page est le
chunk**. C'est précisément la thèse que ColPali défend.

### Pourquoi les spans restent comparables

Le juge note la récupération en intervalles `[char_start, char_end)` sur le
document source. Une page image n'a pas de caractères — donc `VisualCorpus`
porte les deux moitiés : chaque `PageRef` sait où son texte extrait vit dans
le texte du document parent. ColPali classe sur les pixels et **rapporte
sur les caractères**, donc son Recall@K veut dire exactement la même chose
que celui de LangChain.

Bonus : ces offsets sont exacts par construction, alors que les moteurs
texte les retrouvent par `str.find()` (`engines/base.locate_span`).
`unlocated_span_count` est structurellement toujours 0 pour ColPali.

## Les deux prérequis avant mise en service

### 1. Un corpus PDF

`mcp_servers/corpus/` est **vide aujourd'hui**, et `FixedCorpus` ne lit que
`*.md`. ColPali n'a donc rien à récupérer. Il faut y déposer des PDF qui
justifient le paradigme — des documents où l'information vit dans des
tableaux, des schémas, une mise en page — sinon ColPali n'a aucun avantage
à démontrer et la comparaison ne dit rien.

`VisualCorpus` sert aussi les moteurs texte (`iter_documents()` rend des
`CorpusDocument` ordinaires), donc un seul corpus PDF suffit pour les six.

### 2. Une validation contre les vrais poids

Le backend `TransformersColPaliBackend` n'a **jamais tourné contre un vrai
modèle** : le réseau de l'environnement de développement bloque
`huggingface.co`. Ce qui reste à vérifier :

- l'API exacte de `colpali_engine.models` pour l'architecture choisie
  (`ColIdefics3` / `ColIdefics3Processor` pour colSmol) ;
- la latence CPU réelle à l'indexation et à la requête — le smoke test de
  l'arène exige une réponse en moins de 60 s ;
- que `vidore/colSmol-256M` tient dans l'image Railway.

```bash
pip install -r mcp_servers/rag_pill/requirements-colpali.txt
COLPALI_ENABLED=1 python -m mcp_servers.rag_pill.server
```

## Choix du modèle

| Modèle | Taille | Pour qui |
|---|---|---|
| `vidore/colSmol-256M` (défaut) | 256M | CPU, Railway sans GPU |
| `vidore/colpali-v1.3` | ~3B | GPU disponible, qualité de référence |

Bascule via `COLPALI_MODEL_ID` + l'argument `architecture` du backend
(`idefics3` pour colSmol, `paligemma` pour colpali-v1.x, `qwen2` pour
ColQwen2).

## Limite connue : les documents uploadés

ColPali **ne fonctionne pas sur un upload utilisateur**, et ce n'est pas un
réglage mais une propriété de l'architecture actuelle :
`backend/tool_arena/document/read_uploaded_file_as_text.py` aplatit le PDF
avec `pypdf` **à la frontière du backend**, et le contrat MCP est
`document_content: str`. Les pixels n'existent déjà plus quand l'outil est
appelé.

Ouvrir ce chemin est un chantier distinct, qui touche trois couches :

1. le frontend doit envoyer les octets du PDF, pas le texte extrait ;
2. le contrat MCP doit gagner un paramètre binaire (`document_b64`, ou une
   URL servie par le backend) ;
3. `EphemeralCorpus` doit avoir un équivalent visuel.

Tant que ce n'est pas fait, ColPali ne concourt qu'en **mode corpus**.

## Coûts et déploiement

`requirements-colpali.txt` n'est **pas** inclus dans l'agrégateur
`requirements.txt` : torch pèse ~2,5 Go à lui seul, et les cinq autres
moteurs n'ont pas à payer pour un paradigme qu'ils n'utilisent pas. Le
moteur n'est instancié que si `COLPALI_ENABLED=1`. Un déploiement qui
n'installe pas ce fichier garde l'image légère et tourne simplement sans.
