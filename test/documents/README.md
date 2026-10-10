# Document de test pour l'arène

`documents/manuel_station_pompage.md` — un manuel de maintenance fictif
(5 200 caractères), écrit pour rendre visible la différence entre les moteurs
de recherche de l'arène.

Il vit dans `documents/` et il est inscrit dans `documents_index.json`, donc
le backend le sert via `GET /tool-arena/documents`.

## Comment s'en servir

1. Ouvrir la Tool Arena, choisir la tâche **Question / Réponse**.
2. Déposer `documents/manuel_station_pompage.md` (le format `.md` est
   accepté, comme `.txt`, `.pdf` et `.docx`).
3. Poser une des questions ci-dessous et coller la réponse attendue dans le
   champ prévu : elle s'affiche à côté des deux réponses anonymes, ce qui
   permet de juger qui a réellement trouvé.

## Questions, et ce qu'elles mettent à l'épreuve

Les colonnes BM25 sont **mesurées**, pas supposées : le moteur a été exécuté
sur ce document exact, en configuration `qa_precise` (chunks de 500, top_k=3).
La colonne « recherche par sens » est une attente, pas une mesure — elle
dépend d'un appel d'API que l'environnement de développement ne peut pas
faire.

| Question | Réponse attendue | BM25 (mesuré) | Recherche par sens (attendu) |
|---|---|---|---|
| Quelle est la référence du palier arrière de la turbine T3 ? | `PAL-3300-B` | ✅ rang 1 | ⚠️ risque de confusion avec `PAL-3300-A` |
| Que signifie le code défaut E-330 ? | Défaut d'isolement moteur sous 0,5 MΩ ; consignation électrique obligatoire | ✅ rang 1 | ⚠️ un code chiffré ressemble à du bruit |
| Quelle pression doit avoir le vase d'expansion ? | Entre 1,0 et 1,5 bar à froid | ✅ rang 1 | ✅ attendu |
| Que faire si l'eau déborde et gagne le passage où marchent les agents ? | Fermer la vanne V4, consigner, appeler l'astreinte ; ne pas emprunter la passerelle | ✅ rang 1 | ✅ attendu |
| **À quelle fréquence faut-il lubrifier les roulements ?** | Trimestrielle (graissage des paliers de turbine) | ❌ **échoue** | ✅ attendu |
| **Combien de temps faut-il attendre une pièce indisponible ?** | Six semaines (membrane MEM-0475-E en rupture) | ❌ **échoue** | ✅ attendu |

Les deux dernières lignes sont les plus intéressantes : la question ne partage
**aucun mot** avec le document. « Lubrifier » n'y figure pas, le manuel dit
« graissage » ; « roulements » non plus, il dit « paliers ». BM25 cherche des
mots exacts, donc il ne trouve rien — et c'est exactement la faiblesse que la
recherche par sens est censée combler, et que l'hybride est censé rattraper.

## Ce que le document contient délibérément

- **Des références presque identiques** (`PAL-3300-A` / `PAL-3300-B`) : des
  leurres pour la recherche par sens, qui les encode quasiment pareil.
- **Des codes défaut** (`E-204`, `E-207`, `E-330`, `E-451`) : des chaînes
  rares qu'aucun modèle n'a vraiment apprises.
- **Un vocabulaire décalé** entre le texte et les questions naturelles
  (graissage/lubrifier, paliers/roulements, rupture/indisponible).
- **Des tableaux et de la prose** mélangés, pour que le découpage en chunks
  ait un effet visible.

## Un défaut trouvé grâce à ce document

La première exécution a montré que la question sur le code `E-330` ramenait le
tableau des pièces de rechange. Le tokenizer découpait `E-330` en `e` + `330` :
la lettre isolée, présente partout, noyait le signal. Corrigé dans
`engines/lexical.py` — un identifiant contenant un chiffre produit désormais
aussi une forme collée (`e330`), et les lettres isolées sont écartées.
Régression épinglée par `tests/test_lexical.py::test_identifiers_are_kept_whole_as_well_as_split`.
