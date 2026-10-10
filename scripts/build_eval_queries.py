"""
BUT : produire mcp_servers/corpus/evaluation/queries.yaml avec des offsets
de caractères exacts, en localisant des ancres de texte plutôt qu'en les
comptant à la main.

Build the benchmark's ground-truth query catalogue.

    python scripts/build_eval_queries.py

The judge (backend/tool_arena/judge_verdict) scores a retrieval by overlap
between the spans an engine returned and the `expected_spans` listed here.
Those spans are character intervals into the corpus files, so writing them
by hand is a guarantee of silent drift: a one-character edit upstream
invalidates every offset below it, and the judge would quietly score
against the wrong text.

So each expected span is declared as an *anchor* — a literal substring of
the corpus file — and this script resolves it to offsets. An anchor that is
missing, or that appears more than once, fails the build rather than
picking one silently.

The corpus pairs two near-identical station manuals on purpose. Vaux is the
document that answers; Le Breuil has the same structure, the same
vocabulary and different values, so a retriever has to discriminate rather
than land on the only plausible page. Several queries below exist only to
test that discrimination.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "mcp_servers" / "corpus"
TARGET = CORPUS_DIR / "evaluation" / "queries.yaml"

VAUX = "manuel_station_vaux.md"
BREUIL = "manuel_station_breuil.md"
SECURITE = "consignes_securite.md"


@dataclass(frozen=True)
class Anchor:
    doc_id: str
    text: str


@dataclass(frozen=True)
class Query:
    id: str
    query_text: str
    goal_text: str
    anchors: tuple[Anchor, ...]
    notes: str


QUERIES: tuple[Query, ...] = (
    Query(
        id="ref_palier_arriere_vaux",
        query_text=(
            "Quelle est la référence de la pièce de rechange du palier arrière "
            "de la turbine T3 ?"
        ),
        goal_text="Donner la référence exacte, telle qu'elle figure au magasin.",
        anchors=(Anchor(VAUX, "| Palier arrière turbine T3 | PAL-3300-B | 1 |"),),
        notes=(
            "Un saut. Deux pièges : PAL-3300-A est le palier *avant*, une ligne "
            "plus haut, et Le Breuil a son propre palier arrière PAL-2100-D. "
            "Une récupération dense encode ces trois lignes presque pareil."
        ),
    ),
    Query(
        id="seuil_arret_immediat_vaux",
        query_text=(
            "À partir de quel niveau de vibration faut-il arrêter immédiatement "
            "une machine à Vaux-sur-Orge ?"
        ),
        goal_text="Donner la valeur du seuil et le code défaut associé.",
        anchors=(
            Anchor(VAUX, "| E-207 | Niveau vibratoire supérieur à 9,0 mm/s |"),
        ),
        notes=(
            "Un saut, mais la même ligne existe au Breuil avec 11,0 mm/s. "
            "Répondre sans distinguer les deux sites donne la mauvaise valeur."
        ),
    ),
    Query(
        id="pression_vase_vaux",
        query_text=(
            "Entre quelles valeurs doit rester la pression du vase d'expansion "
            "à Vaux-sur-Orge ?"
        ),
        goal_text="Donner l'intervalle de pression à froid.",
        anchors=(
            Anchor(VAUX, "doit rester comprise entre 1,0 et 1,5 bar à\nfroid"),
        ),
        notes="Un saut. Le Breuil annonce 0,8 à 1,2 bar — même phrase, autres valeurs.",
    ),
    Query(
        id="consignation_defaut_isolement",
        query_text=(
            "Que faut-il faire avant d'intervenir quand un défaut d'isolement "
            "est détecté ?"
        ),
        goal_text="Donner la procédure obligatoire.",
        anchors=(
            Anchor(
                SECURITE,
                "Un défaut d'isolement avéré interdit toute intervention avant "
                "consignation",
            ),
        ),
        notes=(
            "Un saut, mais hors du manuel : la règle vit dans les consignes "
            "communes. Les deux manuels mentionnent le code E-330 sans donner "
            "la procédure, donc s'arrêter au manuel rate la réponse."
        ),
    ),
    Query(
        id="piece_organe_hors_seuil_multihop",
        query_text=(
            "Quelle pièce faut-il commander pour l'organe de Vaux-sur-Orge qui "
            "a dépassé son seuil d'alerte le 14 mars ?"
        ),
        goal_text="Donner la référence de la pièce concernée.",
        anchors=(
            Anchor(VAUX, "Turbine T3 à 7,2 mm/s, au-delà du seuil"),
            Anchor(VAUX, "| Palier arrière turbine T3 | PAL-3300-B | 1 |"),
        ),
        notes=(
            "DEUX SAUTS. Le journal dit quel organe a dépassé (T3) ; le tableau "
            "des pièces donne la référence du palier arrière (PAL-3300-B). Les "
            "deux passages sont dans des sections différentes et ne partagent "
            "presque aucun mot avec la question. Un moteur qui n'en ramène qu'un "
            "plafonne à Recall@K = 0,5."
        ),
    ),
    Query(
        id="passerelle_deversement_multihop",
        query_text=(
            "Un agent peut-il emprunter la passerelle de Vaux-sur-Orge pendant "
            "un déversement, et pourquoi ?"
        ),
        goal_text="Donner la consigne et sa justification.",
        anchors=(
            Anchor(VAUX, "Ne jamais emprunter la passerelle\ntant que le déversement n'a pas cessé"),
            Anchor(
                SECURITE,
                "Les passerelles de service ne sont pas praticables lorsqu'un "
                "déversement est\nen cours",
            ),
        ),
        notes=(
            "DEUX SAUTS, et entre deux documents : l'interdiction est dans le "
            "manuel du site, la raison dans les consignes communes. Mesure si "
            "un moteur sait rapporter deux sources plutôt qu'une."
        ),
    ),
)


def _resolve(anchor: Anchor) -> tuple[int, int]:
    path = CORPUS_DIR / anchor.doc_id
    if not path.exists():
        raise SystemExit(f"[FAIL] corpus file missing: {path}")
    text = path.read_text(encoding="utf-8")
    occurrences = text.count(anchor.text)
    if occurrences == 0:
        raise SystemExit(
            f"[FAIL] anchor not found in {anchor.doc_id}:\n  {anchor.text!r}"
        )
    if occurrences > 1:
        raise SystemExit(
            f"[FAIL] anchor appears {occurrences}x in {anchor.doc_id} — "
            f"ambiguous, lengthen it:\n  {anchor.text!r}"
        )
    start = text.index(anchor.text)
    return start, start + len(anchor.text)


def _yaml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render() -> str:
    lines = [
        "# GENERATED by scripts/build_eval_queries.py — do not edit by hand.",
        "# Character offsets are resolved from text anchors; editing a corpus",
        "# file means re-running the script, not patching numbers here.",
        "",
    ]
    for query in QUERIES:
        lines.append(f'- id: "{query.id}"')
        lines.append(f'  query_text: "{_yaml_escape(query.query_text)}"')
        lines.append(f'  goal_text: "{_yaml_escape(query.goal_text)}"')
        lines.append(f'  notes: "{_yaml_escape(query.notes)}"')
        lines.append("  expected_spans:")
        for anchor in query.anchors:
            start, end = _resolve(anchor)
            lines.append(f'    - source_doc_id: "{anchor.doc_id}"')
            lines.append(f"      char_start: {start}")
            lines.append(f"      char_end: {end}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    rendered = render()
    check = "--check" in sys.argv
    if check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != rendered:
            sys.stderr.write(
                "queries.yaml is stale — run scripts/build_eval_queries.py\n"
            )
            return 1
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered, encoding="utf-8")
    multihop = sum(1 for q in QUERIES if len(q.anchors) > 1)
    sys.stderr.write(
        f"wrote {TARGET.relative_to(ROOT)} — {len(QUERIES)} questions "
        f"({multihop} à plusieurs sauts)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
