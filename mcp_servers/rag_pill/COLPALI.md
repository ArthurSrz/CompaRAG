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

### 1. Un corpus PDF — ✅ fait, à déplacer

Quatre documents générés vivent dans `test/pdfs/` (voir `test/README.md`) :
un tableau + graphique, un schéma annoté, un formulaire deux colonnes, et
un scan sans aucune couche texte. Ils servent les tests.

Reste à décider ce qui devient le corpus **de l'arène** : `mcp_servers/corpus/`
est toujours vide et `FixedCorpus` n'y lit que `*.md`, donc le mode corpus
est inerte pour tout le monde aujourd'hui, pas seulement pour ColPali.

`VisualCorpus` sert aussi les moteurs texte (`iter_documents()` rend des
`CorpusDocument` ordinaires), donc un seul corpus PDF suffit pour les six.

### 2a. Option retenue : inférence hébergée (API)

`HTTPColPaliBackend` appelle un endpoint distant au lieu de charger les
poids. Le moteur ne voit aucune différence : même Protocol, mêmes tableaux
retournés. L'image reste légère (pas de torch), il n'y a pas de chargement
à froid, et aucun GPU à provisionner.

```bash
COLPALI_ENABLED=1 \
COLPALI_ENDPOINT_URL=https://<endpoint>.endpoints.huggingface.cloud \
HF_TOKEN=hf_... \
python -m mcp_servers.rag_pill.server
```

Deux points à régler avant que ça marche :

- **ColPali n'est pas une tâche standard** de l'API d'inférence gratuite de
  Hugging Face : il renvoie plusieurs vecteurs par page, ce qu'aucun
  pipeline classique n'expose. Il faut très probablement un *Inference
  Endpoint* dédié (payant, à provisionner) avec un petit handler maison.
- **La forme exacte de la réponse n'est pas confirmée.** `_as_multivector`
  accepte les trois encodages plausibles et **échoue bruyamment** sinon —
  en particulier si l'endpoint renvoie un seul vecteur moyenné, auquel cas
  l'interaction tardive aurait disparu sans que rien ne le signale. Un seul
  appel réel tranche la question.

### 2b. Validation contre les vrais poids

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

## Limite connue : répondre depuis un scan

ColPali sait **trouver** une page scannée — c'est tout l'intérêt. Mais ce
moteur passe ensuite le *texte* de la page au LLM, et un scan n'en a pas :
le LLM reçoit une chaîne vide. La récupération est juste, la réponse est
vide. C'est épinglé par
`tests/test_colpali_on_test_pdfs.py::test_retrieving_a_scanned_page_hands_the_llm_nothing`.

Deux sorties possibles, à trancher :

- **Envoyer l'image au LLM.** `mistral-medium-3.1` est multimodal. La parité
  tient (même modèle pour tous), seule la modalité du contexte change — et
  c'est sans doute le vrai pipeline ColPali. À vérifier contre OpenRouter.
- **OCR de repli** sur les pages retenues sans couche texte. Plus simple,
  mais on réintroduit l'extraction que ColPali était censé éviter.

Tant que ce n'est pas fait, l'avantage de ColPali se joue sur les tableaux,
les schémas et les mises en page — pas sur les scans purs.

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
