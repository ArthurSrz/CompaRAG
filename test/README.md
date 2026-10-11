# Corpus PDF de test

Cinq documents générés, où l'information vit dans la **forme** et pas
seulement dans les mots.

Ils ont été construits pour un moteur visuel (ColPali), projet annulé le
2026-10-11 — voir `.planning/STATE.md`. Ils restent utiles pour deux raisons
indépendantes : `manuel_station_pompage.pdf` sert aux essais d'interface sur
BM25 (fiche de questions plus bas), et `rapport_scanne.pdf` documente ce que
l'extraction de texte perd — zéro caractère sur un document parfaitement
lisible à l'œil.

Régénérer :

```bash
python scripts/build_test_pdfs.py
```

Ils sont générés plutôt que déposés comme des binaires opaques : on peut
lire dans le script ce que chaque page est censée contenir, et les
reconstruire à l'identique.

| Document | Pages | Texte extractible | Ce qu'il met à l'épreuve |
|---|---|---|---|
| `rapport_trimestriel.pdf` | 2 | 661 car. | Un tableau réglé et un graphique à barres. Le texte sort, mais la **structure** du tableau se dissout : les chiffres perdent leur ligne et leur colonne. |
| `notice_technique.pdf` | 2 | 933 car. | Un schéma annoté. Les étiquettes sortent ; **ce qu'elles désignent**, non. |
| `formulaire_adhesion.pdf` | 1 | 409 car. | Un formulaire sur deux colonnes. L'extraction mélange l'ordre de lecture : un champ et sa valeur se séparent. |
| `rapport_scanne.pdf` | 2 | **0 car.** | Un scan. Chaque page est une photographie de texte : l'extraction ne rend **rien**. |

La dernière ligne est le cas témoin, et elle reste vraie sans ColPali : un
moteur texte qui indexe ce document obtient zéro, par construction. C'est la
limite du paradigme en vigueur dans l'arène, mesurée plutôt qu'affirmée.
