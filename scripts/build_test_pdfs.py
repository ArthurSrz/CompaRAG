"""
BUT : fabriquer un petit corpus PDF où l'information vit dans la FORME —
tableaux, graphiques, schémas, page scannée — pour que les moteurs visuels
aient quelque chose à montrer que les moteurs texte ne peuvent pas voir.

Build the visual test corpus into test/pdfs/.

    python scripts/build_test_pdfs.py

Generated rather than committed as opaque binaries: a reviewer can read
what each page is supposed to contain, and regenerate it byte-for-byte.

The four documents escalate in how much they punish text extraction:

1. rapport_trimestriel.pdf — a table and a bar chart. Extractable as text,
   but the table's *structure* collapses into a word soup once flattened.
2. notice_technique.pdf — a labelled diagram. The labels extract; what they
   point at does not.
3. formulaire_adhesion.pdf — a multi-column form. Extraction scrambles the
   reading order, so a field and its value drift apart.
4. rapport_scanne.pdf — a scan. Every page is a photograph of text, so
   extraction returns essentially nothing. This is the control case: any
   text engine scores zero here by construction.
"""

from __future__ import annotations

import io
import random
from pathlib import Path

import pymupdf

OUT_DIR = Path(__file__).resolve().parent.parent / "test" / "pdfs"

A4 = pymupdf.paper_rect("a4")
MARGIN = 56
INK = (0.1, 0.1, 0.12)
ACCENT = (0.18, 0.35, 0.62)
GREY = (0.55, 0.55, 0.58)


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------

# PyMuPDF's base-14 fonts are Latin-1 encoded: anything outside it draws as
# "?" or a wrong glyph. Map the typographic characters this corpus uses onto
# ASCII once, centrally, rather than policing every literal.
_LATIN1_SUBSTITUTIONS = {
    "\u2014": "-",
    "\u2013": "-",
    "\u20ac": " EUR",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
}


def _latin1(text: str) -> str:
    for source, replacement in _LATIN1_SUBSTITUTIONS.items():
        text = text.replace(source, replacement)
    return text.encode("latin-1", "replace").decode("latin-1")


def _title(page, text: str, y: float = 70) -> float:
    page.insert_text((MARGIN, y), _latin1(text), fontsize=19, fontname="hebo", color=INK)
    page.draw_line(
        pymupdf.Point(MARGIN, y + 10),
        pymupdf.Point(A4.width - MARGIN, y + 10),
        color=ACCENT,
        width=1.4,
    )
    return y + 38


def _paragraph(page, text: str, y: float, size: int = 10.5) -> float:
    rect = pymupdf.Rect(MARGIN, y, A4.width - MARGIN, y + 160)
    overflow = page.insert_textbox(
        rect, _latin1(text), fontsize=size, fontname="helv", color=INK, align=0
    )
    used = 160 - max(overflow, 0)
    return y + used + 16


def _table(page, headers, rows, y: float, col_widths=None) -> float:
    """Draw a ruled table. The point of the fixture: the *grid* carries the
    meaning, and flattening to text destroys it."""
    width = A4.width - 2 * MARGIN
    n = len(headers)
    col_widths = col_widths or [width / n] * n
    row_h = 22

    x = MARGIN
    page.draw_rect(
        pymupdf.Rect(MARGIN, y, MARGIN + sum(col_widths), y + row_h),
        fill=(0.91, 0.93, 0.97),
        color=None,
    )
    for header, w in zip(headers, col_widths):
        page.insert_text(
            (x + 6, y + 15), _latin1(header), fontsize=9.5, fontname="hebo", color=INK
        )
        x += w

    cursor = y + row_h
    for row in rows:
        x = MARGIN
        for cell, w in zip(row, col_widths):
            page.insert_text(
                (x + 6, cursor + 15), _latin1(str(cell)), fontsize=9.5,
                fontname="helv", color=INK
            )
            x += w
        page.draw_line(
            pymupdf.Point(MARGIN, cursor),
            pymupdf.Point(MARGIN + sum(col_widths), cursor),
            color=(0.85, 0.85, 0.88),
            width=0.6,
        )
        cursor += row_h

    page.draw_rect(
        pymupdf.Rect(MARGIN, y, MARGIN + sum(col_widths), cursor),
        color=(0.7, 0.7, 0.75),
        width=0.8,
    )
    x = MARGIN
    for w in col_widths[:-1]:
        x += w
        page.draw_line(
            pymupdf.Point(x, y), pymupdf.Point(x, cursor),
            color=(0.85, 0.85, 0.88), width=0.6,
        )
    return cursor + 22


def _bar_chart_png(categories, series, title: str) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, ax = plt.subplots(figsize=(6.4, 3.4), dpi=120)
    x = np.arange(len(categories))
    width = 0.8 / len(series)
    for i, (label, values) in enumerate(series.items()):
        ax.bar(x + i * width - 0.4 + width / 2, values, width, label=label)
    ax.set_xticks(x)
    ax.set_xticklabels(categories)
    ax.set_title(title, fontsize=11)
    ax.set_ylabel("k€")
    ax.legend(fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    return buffer.getvalue()


def _ascii_fold(text: str) -> str:
    """Strip accents and typographic punctuation. PIL's default font has no
    glyphs for either and draws tofu boxes; a typewritten page is a plausible
    place to lose them."""
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", _latin1(text))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _scan_jpeg(lines: list[str], seed: int) -> bytes:
    """Render text as a photographed page: rotated, speckled, greyish.

    No text layer at all — the only way in is to look at it.

    JPEG rather than PNG, for the same reason a real scanner uses it: the
    speckle defeats lossless compression, and PNG blew the fixture up to
    13 MB. A scan is a photograph; store it like one.
    """
    from PIL import Image, ImageDraw, ImageFont

    rng = random.Random(seed)
    width, height = 1240, 1754  # A4 at 150 dpi
    canvas = Image.new("RGB", (width, height), (247, 245, 240))
    draw = ImageDraw.Draw(canvas)

    try:
        title_font = ImageFont.load_default(size=44)
        body_font = ImageFont.load_default(size=27)
    except TypeError:  # Pillow < 10.1
        title_font = body_font = ImageFont.load_default()

    y = 150
    for index, line in enumerate(lines):
        font = title_font if index == 0 else body_font
        draw.text((120, y), _ascii_fold(line), fill=(28, 28, 34), font=font)
        y += 70 if index == 0 else 44

    for _ in range(9000):  # scanner speckle
        px, py = rng.randrange(width), rng.randrange(height)
        shade = rng.randint(170, 225)
        canvas.putpixel((px, py), (shade, shade, shade - 6))

    canvas = canvas.rotate(0.8, resample=Image.BICUBIC, fillcolor=(247, 245, 240))

    buffer = io.BytesIO()
    canvas.save(buffer, format="JPEG", quality=80, optimize=True)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# documents
# --------------------------------------------------------------------------

REGIONS = ("Nord", "Sud", "Est", "Ouest")
QUARTERS = ("T1", "T2", "T3", "T4")
REVENUE = {
    "Nord": (1420, 1510, 1380, 1690),
    "Sud": (1870, 1940, 2110, 2340),
    "Est": (980, 1040, 1120, 1210),
    "Ouest": (1330, 1290, 1405, 1520),
}


def build_rapport_trimestriel(path: Path) -> None:
    doc = pymupdf.open()

    page = doc.new_page()
    y = _title(page, "Rapport trimestriel 2025 — Chiffre d'affaires")
    y = _paragraph(
        page,
        "Le présent rapport consolide le chiffre d'affaires des quatre régions "
        "commerciales sur l'exercice 2025. Les montants sont exprimés en "
        "milliers d'euros et hors taxes. Le détail par région et par trimestre "
        "figure dans le tableau ci-dessous.",
        y,
    )
    _table(
        page,
        ["Région", *QUARTERS, "Total"],
        [[r, *REVENUE[r], sum(REVENUE[r])] for r in REGIONS],
        y,
        col_widths=[110, 70, 70, 70, 70, 93],
    )

    page = doc.new_page()
    y = _title(page, "Évolution trimestrielle par région")
    png = _bar_chart_png(
        list(QUARTERS),
        {region: list(REVENUE[region]) for region in REGIONS},
        "Chiffre d'affaires par trimestre et par région",
    )
    page.insert_image(pymupdf.Rect(MARGIN, y, A4.width - MARGIN, y + 300), stream=png)
    _paragraph(
        page,
        "La région Sud franchit le seuil des 2 millions d'euros au troisième "
        "trimestre et confirme sa progression au quatrième. La région Est reste "
        "la plus faible contributrice sur l'ensemble de l'exercice.",
        y + 318,
    )

    doc.save(path)
    doc.close()


def build_notice_technique(path: Path) -> None:
    doc = pymupdf.open()

    page = doc.new_page()
    y = _title(page, "Notice technique — Pompe de circulation PC-480")
    y = _paragraph(
        page,
        "Avant toute intervention, couper l'alimentation électrique et vidanger "
        "le circuit. Le schéma ci-dessous identifie les organes accessibles sans "
        "dépose complète de l'appareil.",
        y,
    )

    # Labelled diagram: boxes connected by arrows. The labels extract as text;
    # which box each one sits in does not.
    boxes = [
        ("A — Corps de pompe", MARGIN + 10, y + 20),
        ("B — Moteur", MARGIN + 210, y + 20),
        ("C — Vase d'expansion", MARGIN + 10, y + 110),
        ("D — Purgeur", MARGIN + 210, y + 110),
    ]
    for label, bx, by in boxes:
        rect = pymupdf.Rect(bx, by, bx + 170, by + 54)
        page.draw_rect(rect, color=ACCENT, width=1.1, fill=(0.96, 0.97, 1.0))
        page.insert_textbox(
            rect + (6, 16, -6, 0), _latin1(label), fontsize=9, fontname="helv", color=INK
        )
    page.draw_line(
        pymupdf.Point(MARGIN + 180, y + 47),
        pymupdf.Point(MARGIN + 210, y + 47),
        color=GREY, width=1.1,
    )
    page.draw_line(
        pymupdf.Point(MARGIN + 95, y + 74),
        pymupdf.Point(MARGIN + 95, y + 110),
        color=GREY, width=1.1,
    )

    _table(
        page,
        ["Caractéristique", "Valeur", "Unité"],
        [
            ["Débit nominal", "4,8", "m³/h"],
            ["Hauteur manométrique", "6,2", "m"],
            ["Pression de service max.", "10", "bar"],
            ["Température fluide", "-10 à +110", "°C"],
            ["Puissance absorbée", "180", "W"],
            ["Indice de protection", "IP44", "—"],
        ],
        y + 200,
        col_widths=[250, 130, 103],
    )

    page = doc.new_page()
    y = _title(page, "Entretien périodique")
    _paragraph(
        page,
        "Purger le circuit tous les six mois à l'aide du purgeur (repère D). "
        "Contrôler annuellement la pression du vase d'expansion (repère C) : "
        "elle doit rester comprise entre 1,0 et 1,5 bar à froid. Un écart "
        "persistant signale une membrane percée et impose le remplacement du "
        "vase. Le corps de pompe (repère A) ne nécessite aucun entretien "
        "courant ; en cas de bruit anormal, vérifier l'alignement du moteur "
        "(repère B) avant toute dépose.",
        y,
    )

    doc.save(path)
    doc.close()


def build_formulaire_adhesion(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    y = _title(page, "Formulaire d'adhésion — Exercice 2026")

    left = pymupdf.Rect(MARGIN, y, A4.width / 2 - 10, y + 230)
    right = pymupdf.Rect(A4.width / 2 + 10, y, A4.width - MARGIN, y + 230)
    for rect, heading, fields in (
        (
            left,
            "Partie réservée à l'adhérent",
            ["Nom :", "Prénom :", "Date de naissance :", "Courriel :", "Téléphone :"],
        ),
        (
            right,
            "Partie réservée à l'administration",
            ["N° de dossier :", "Date de réception :", "Agent instructeur :",
             "Cotisation appelée :", "Décision :"],
        ),
    ):
        page.draw_rect(rect, color=(0.8, 0.8, 0.84), width=0.9)
        page.insert_text(
            (rect.x0 + 8, rect.y0 + 18), _latin1(heading),
            fontsize=9.5, fontname="hebo", color=ACCENT,
        )
        cursor = rect.y0 + 44
        for field in fields:
            page.insert_text(
                (rect.x0 + 8, cursor), _latin1(field), fontsize=9, fontname="helv", color=INK
            )
            page.draw_line(
                pymupdf.Point(rect.x0 + 8, cursor + 16),
                pymupdf.Point(rect.x1 - 8, cursor + 16),
                color=(0.85, 0.85, 0.88), width=0.6,
            )
            cursor += 36

    y += 254
    page.insert_text(
        (MARGIN, y), _latin1("Type d'adhésion (cocher une seule case)"),
        fontsize=9.5, fontname="hebo", color=INK,
    )
    y += 20
    for label, checked in (
        ("Individuelle — 45 euros", False),
        ("Couple — 70 euros", True),
        ("Association — 120 euros", False),
        ("Tarif réduit (étudiant, demandeur d'emploi) — 20 euros", False),
    ):
        box = pymupdf.Rect(MARGIN, y - 9, MARGIN + 11, y + 2)
        page.draw_rect(box, color=INK, width=0.9)
        if checked:
            page.draw_line(pymupdf.Point(box.x0 + 2, box.y0 + 5),
                           pymupdf.Point(box.x0 + 4.5, box.y1 - 2),
                           color=INK, width=1.3)
            page.draw_line(pymupdf.Point(box.x0 + 4.5, box.y1 - 2),
                           pymupdf.Point(box.x1 - 1, box.y0 + 1),
                           color=INK, width=1.3)
        page.insert_text(
            (MARGIN + 20, y), _latin1(label), fontsize=9, fontname="helv", color=INK
        )
        y += 22

    doc.save(path)
    doc.close()


def build_rapport_scanne(path: Path) -> None:
    """The control case: a photographed document, with no text layer."""
    doc = pymupdf.open()
    pages = [
        [
            "COMPTE RENDU DE VISITE",
            "Site : station de traitement de Vaux-sur-Orge",
            "Date : 14 mars 2025        Rédacteur : M. Berthier",
            "",
            "La turbine n°3 presente un jeu anormal sur le palier",
            "arriere. Le niveau vibratoire releve atteint 7,2 mm/s,",
            "au-dela du seuil d'alerte fixe a 4,5 mm/s.",
            "",
            "Preconisation : arret programme sous quinzaine et",
            "remplacement du palier. Piece de rechange disponible",
            "en magasin sous la reference PAL-3300-B.",
        ],
        [
            "ANNEXE — RELEVES DE VIBRATION",
            "",
            "Turbine 1 : 2,1 mm/s        conforme",
            "Turbine 2 : 3,8 mm/s        conforme",
            "Turbine 3 : 7,2 mm/s        HORS SEUIL",
            "Turbine 4 : 2,6 mm/s        conforme",
            "",
            "Seuil d'alerte : 4,5 mm/s",
            "Seuil d'arret immediat : 9,0 mm/s",
            "",
            "Prochain releve prevu le 11 avril 2025.",
        ],
    ]
    for index, lines in enumerate(pages):
        page = doc.new_page()
        page.insert_image(A4, stream=_scan_jpeg(lines, seed=1000 + index))
    doc.save(path)
    doc.close()


def build_manuel_station_pompage(path: Path) -> None:
    """The PDF twin of documents/manuel_station_pompage.md.

    Same content, laid out as a real document so it exercises the arena's
    PDF upload path (pypdf extraction) rather than the plain-text one. The
    part references and fault codes are what BM25 is here to find, so the
    tables must survive extraction with their values intact.
    """
    doc = pymupdf.open()

    page = doc.new_page()
    y = _title(page, "Manuel de maintenance - Station de pompage")
    y = _paragraph(
        page,
        "Document interne. Version 4.2 - mise a jour du 14 mars 2025. "
        "Redacteur : M. Berthier, responsable exploitation. La station comporte "
        "quatre organes principaux, reperes sur le synoptique du local "
        "technique. Chaque numero de serie est grave sur la plaque "
        "signaletique fixee au carter.",
        y,
    )
    y = _table(
        page,
        ["Repere", "Equipement", "Numero de serie", "Mise en service"],
        [
            ["P1", "Pompe de relevage n1", "VX-88114-A", "juin 2018"],
            ["P2", "Pompe de relevage n2", "VX-88115-A", "juin 2018"],
            ["T3", "Turbine de recirculation", "VX-21007-C", "mars 2021"],
            ["V4", "Vanne motorisee amont", "VX-44902-M", "mars 2021"],
        ],
        y,
        col_widths=[70, 180, 130, 103],
    )
    y = _paragraph(
        page,
        "Pieces de rechange referencees. Les references ci-dessous sont celles "
        "du magasin central. Toute commande doit mentionner la reference "
        "exacte : plusieurs organes se ressemblent et ne sont pas "
        "interchangeables.",
        y,
    )
    _table(
        page,
        ["Organe", "Reference", "Stock magasin"],
        [
            ["Palier avant turbine T3", "PAL-3300-A", "2"],
            ["Palier arriere turbine T3", "PAL-3300-B", "1"],
            ["Garniture mecanique P1 / P2", "GAR-1180-K", "4"],
            ["Membrane de vase d'expansion", "MEM-0475-E", "0"],
            ["Carte de commande V4", "CMD-7720-R", "1"],
            ["Joint torique de bride DN150", "JTO-0150-N", "12"],
        ],
        y,
        col_widths=[250, 130, 103],
    )

    page = doc.new_page()
    y = _title(page, "Seuils d'alarme et codes defaut")
    y = _paragraph(
        page,
        "L'automate remonte les defauts sous forme de codes a trois chiffres "
        "precedes de la lettre E. Un code actif s'affiche en rouge sur le "
        "pupitre et declenche l'envoi d'un message a l'astreinte.",
        y,
    )
    y = _table(
        page,
        ["Code", "Condition", "Conduite a tenir"],
        [
            ["E-204", "Vibration superieure a 4,5 mm/s", "Alerte. Controle sous quinzaine."],
            ["E-207", "Vibration superieure a 9,0 mm/s", "Arret immediat de la machine."],
            ["E-112", "Temperature de palier > 85 C", "Arret immediat. Verifier le graissage."],
            ["E-330", "Isolement moteur < 0,5 MOhm", "Consignation electrique obligatoire."],
            ["E-451", "Perte du capteur de niveau amont", "Commande manuelle. Surveillance."],
        ],
        y,
        col_widths=[70, 200, 213],
    )
    y = _paragraph(
        page,
        "Conduite a tenir en cas d'incident. Lorsque le niveau amont franchit "
        "la cote 12,40 m NGF alors que les deux pompes tournent deja, "
        "l'excedent s'evacue par le trop-plein vers le bassin tampon. Si le "
        "deversement gagne la passerelle de service, fermer la vanne motorisee "
        "V4, consigner l'installation et prevenir l'astreinte au "
        "06 12 34 56 78. Ne jamais emprunter la passerelle tant que le "
        "deversement n'a pas cesse.",
        y,
    )
    _paragraph(
        page,
        "Demarrage impossible d'une pompe : verifier dans l'ordre la position "
        "du sectionneur, la presence du code E-330, l'etat du relais thermique, "
        "puis la rotation libre de l'arbre. Si l'arbre ne tourne pas "
        "librement, ne pas forcer : la garniture mecanique est probablement "
        "grippee.",
        y,
    )

    page = doc.new_page()
    y = _title(page, "Entretien periodique et journal")
    y = _table(
        page,
        ["Operation", "Periodicite", "Duree"],
        [
            ["Releve vibratoire des quatre organes", "Mensuelle", "45 min"],
            ["Graissage des paliers de turbine", "Trimestrielle", "1 h"],
            ["Controle pression du vase d'expansion", "Semestrielle", "30 min"],
            ["Mesure d'isolement des moteurs", "Annuelle", "2 h"],
            ["Epreuve du clapet anti-retour", "Annuelle", "3 h"],
        ],
        y,
        col_widths=[280, 110, 93],
    )
    y = _paragraph(
        page,
        "La pression du vase d'expansion doit rester comprise entre 1,0 et "
        "1,5 bar a froid. Un ecart persistant signale une membrane percee et "
        "impose le remplacement du vase complet. La membrane MEM-0475-E est en "
        "rupture depuis janvier 2025 ; delai annonce par le fournisseur : six "
        "semaines.",
        y,
    )
    _paragraph(
        page,
        "Journal des interventions. 14 mars 2025 : releve vibratoire, turbine "
        "T3 a 7,2 mm/s, au-dela du seuil d'alerte. Preconisation : arret "
        "programme sous quinzaine et remplacement du palier arriere, reference "
        "PAL-3300-B, disponible en magasin. 8 fevrier 2025 : remplacement de "
        "la garniture mecanique de P2, reference GAR-1180-K. 19 janvier 2025 : "
        "apparition du code E-451 pendant quatre heures, capteur encrasse. "
        "6 decembre 2024 : controle d'isolement annuel, P1 a 42 MOhm, P2 a "
        "38 MOhm, T3 a 51 MOhm.",
        y,
    )

    doc.save(path)
    doc.close()


BUILDERS = {
    "rapport_trimestriel.pdf": build_rapport_trimestriel,
    "notice_technique.pdf": build_notice_technique,
    "formulaire_adhesion.pdf": build_formulaire_adhesion,
    "rapport_scanne.pdf": build_rapport_scanne,
    "manuel_station_pompage.pdf": build_manuel_station_pompage,
}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, builder in BUILDERS.items():
        target = OUT_DIR / filename
        builder(target)
        with pymupdf.open(target) as doc:
            chars = sum(len(page.get_text()) for page in doc)
            print(f"{filename:<28} {len(doc)} page(s)  {chars:>5} chars extractable")
    print(f"\nwrote {len(BUILDERS)} PDFs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
