# Corpus PDF de test

Quatre documents générés, où l'information vit dans la **forme** et pas
seulement dans les mots. C'est le corpus qui permet de faire concourir un
moteur visuel (ColPali) contre les moteurs texte.

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

La dernière ligne est le cas témoin. Elle démontre l'écart que ColPali
existe pour combler, sans avoir besoin du modèle : un moteur texte qui
indexe ce document obtient zéro, par construction.

Les tests qui s'appuient sur ce corpus sont dans
`mcp_servers/rag_pill/tests/test_colpali_on_test_pdfs.py`.
