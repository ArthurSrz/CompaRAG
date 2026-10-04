"""
BUT : garantir que PageIndex reçoive toujours un markdown à titres.

``md_to_tree`` (upstream) ne construit des nœuds qu'à partir des lignes
``# Titre``. Deux conséquences silencieuses :

  1. un document sans aucun titre (tout .txt, la plupart des PDF/DOCX
     extraits) donne ``structure: []`` → le LLM répond « document vide » ;
  2. le texte situé AVANT le premier titre n'appartient à aucun nœud et
     disparaît de l'arbre.

``ensure_sections`` corrige les deux sans dépendance externe (testable sans
le package vendored) :
  - pas de titre → sections synthétiques d'environ ``target_chars``
    caractères, découpées aux frontières de paragraphes ;
  - préambule non vide avant le premier titre → titre « Préambule » ajouté.
"""
from __future__ import annotations

import re

# Mêmes règles que pageindex.page_index_md.extract_nodes_from_markdown.
_HEADER = re.compile(r"^(#{1,6})\s+(.+)$")
_FENCE = re.compile(r"^```")

DEFAULT_TARGET_CHARS = 2000
_TITLE_WORDS = 8


def _first_heading_line(lines: list[str]) -> int | None:
    in_code = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if _FENCE.match(stripped):
            in_code = not in_code
            continue
        if not in_code and _HEADER.match(stripped):
            return i
    return None


def _paragraphs(text: str) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) == 1:
        # Texte extrait de PDF : souvent aucune ligne vide — retomber sur les lignes.
        paras = [l.strip() for l in text.splitlines() if l.strip()]
    return paras


def _hard_split(para: str, target_chars: int) -> list[str]:
    if len(para) <= target_chars:
        return [para]
    out, buf = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", para):
        if buf and len(buf) + len(sentence) + 1 > target_chars:
            out.append(buf)
            buf = ""
        buf = f"{buf} {sentence}".strip()
        while len(buf) > target_chars:  # phrase plus longue que la cible
            out.append(buf[:target_chars])
            buf = buf[target_chars:]
    if buf:
        out.append(buf)
    return out


def _title_for(chunk: str, index: int) -> str:
    words = re.sub(r"[#*_`>\[\]]", "", chunk).split()
    head = " ".join(words[:_TITLE_WORDS])
    suffix = "…" if len(words) > _TITLE_WORDS else ""
    return f"Section {index} : {head}{suffix}" if head else f"Section {index}"


def _synthetic_sections(text: str, target_chars: int) -> str:
    pieces = [p for para in _paragraphs(text) for p in _hard_split(para, target_chars)]
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for piece in pieces:
        if buf and size + len(piece) > target_chars:
            chunks.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(piece)
        size += len(piece) + 2
    if buf:
        chunks.append("\n\n".join(buf))
    return "\n\n".join(
        f"# {_title_for(chunk, i)}\n\n{chunk}" for i, chunk in enumerate(chunks, 1)
    )


def ensure_sections(text: str, target_chars: int = DEFAULT_TARGET_CHARS) -> str:
    """Retourne un markdown dont tout le contenu appartient à un titre."""
    if not text.strip():
        return text
    lines = text.splitlines()
    first = _first_heading_line(lines)
    if first is None:
        return _synthetic_sections(text, target_chars)
    preamble = "\n".join(lines[:first]).strip()
    if not preamble:
        return text
    rest = "\n".join(lines[first:])
    return f"# Préambule\n\n{preamble}\n\n{rest}"
