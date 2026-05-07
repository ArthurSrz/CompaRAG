"""Build the public arena-tools catalog from utils/news/tools-fr.yaml.

Produces frontend/src/lib/generated/tools.json in the same shape the /news
page consumes, so tool entries flow through the existing card-grid + filter
machinery (see frontend/src/routes/(pages)/news/+page.svelte).

Logos are resolved per entry:
  1. ``logo_local`` set → copy that repo path to frontend/static/tools/{id}{.ext}
  2. ``logo_url`` set → download once on first build (idempotent: if the
     destination file already exists, we skip the network call)

Run via ``make i18n-build-tools`` or directly:
    uv run python -m utils.news.build_tools
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Literal

import httpx
import yaml
from pydantic import BaseModel, RootModel

from utils.utils import FRONTEND_DIR, FRONTEND_GENERATED_DIR, ROOT_DIR, write_json

logger = logging.getLogger("build_tools")

CURRENT_DIR = Path(__file__).parent
SOURCE_FILE = CURRENT_DIR / "tools-fr.yaml"
FRONTEND_EXPORT_FILE = FRONTEND_GENERATED_DIR / "tools.json"
LOGO_DIR = FRONTEND_DIR / "static" / "tools"

# Maps Content-Type to file extension. Falls back to .png for unknown types
# since most logo CDNs serve PNG by default.
_CT_EXT = {
    "image/svg+xml": ".svg",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "image/webp": ".webp",
}


class Tool(BaseModel):
    id: str
    name: str
    sub_kind: Literal["framework", "engine", "hosted"]
    desc: str
    homepage_url: str
    logo_url: str | None = None
    logo_local: str | None = None


ToolList = RootModel[list[Tool]]


def _existing_logo(tool_id: str) -> Path | None:
    """Return path to an already-resolved logo for tool_id, or None."""
    for ext in (".svg", ".png", ".jpg", ".webp", ".ico"):
        candidate = LOGO_DIR / f"{tool_id}{ext}"
        if candidate.exists():
            return candidate
    return None


def _resolve_logo(tool: Tool) -> Path:
    """Materialize the tool's logo under frontend/static/tools/. Idempotent."""
    LOGO_DIR.mkdir(parents=True, exist_ok=True)

    existing = _existing_logo(tool.id)
    if existing is not None:
        logger.info("logo for %s already present at %s", tool.id, existing.name)
        return existing

    if tool.logo_local:
        src = ROOT_DIR / tool.logo_local
        if not src.exists():
            raise FileNotFoundError(
                f"logo_local for {tool.id!r} points at {src} which does not exist"
            )
        dest = LOGO_DIR / f"{tool.id}{src.suffix}"
        shutil.copyfile(src, dest)
        logger.info("copied %s logo from %s", tool.id, src.relative_to(ROOT_DIR))
        return dest

    if tool.logo_url:
        logger.info("fetching %s logo from %s", tool.id, tool.logo_url)
        # follow_redirects=True: GitHub raw URLs and many CDNs redirect.
        resp = httpx.get(tool.logo_url, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        ext = _CT_EXT.get(ct, ".png")
        dest = LOGO_DIR / f"{tool.id}{ext}"
        dest.write_bytes(resp.content)
        return dest

    raise ValueError(f"tool {tool.id!r} has neither logo_local nor logo_url")


def _to_news_card(tool: Tool, logo_path: Path) -> dict:
    """Serialize a Tool into the shape the /news page consumes.

    Mirrors the News schema in build_news.py (kind / subKind / title / desc /
    imgSrc / href / linkLabel) so a tool entry can be concatenated with the
    news feed without runtime mapping.
    """
    return {
        "kind": "tool",
        "subKind": tool.sub_kind,
        "title": tool.name,
        "desc": tool.desc.strip(),
        # Bare filename — the /news page renders with prefix `/tools/` for
        # tool entries (mirroring how it prefixes `/news/` for news images).
        "imgSrc": logo_path.name,
        "href": tool.homepage_url,
        "linkLabel": "Visiter le site",
    }


def main() -> None:
    raw = yaml.safe_load(SOURCE_FILE.read_text())
    tools = ToolList.model_validate(raw)

    cards: list[dict] = []
    for tool in tools.root:
        logo_path = _resolve_logo(tool)
        cards.append(_to_news_card(tool, logo_path))

    write_json(FRONTEND_EXPORT_FILE, cards)
    logger.info("wrote %d tool cards to %s", len(cards), FRONTEND_EXPORT_FILE)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
