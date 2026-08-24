"""Helpers CMS pages publiques (blocs, YouTube, invalidation cache)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from django.db.models import Prefetch
from django.db.utils import OperationalError, ProgrammingError
from django.utils.html import escape, linebreaks

from .models import PageBlock, SitePage

HOME_CACHE_VERSION_KEY = "pages:home:cache_version"
CONCERTS_CACHE_VERSION_KEY = "pages:concerts:cache_version"
YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def _bump_cache_version(key: str) -> None:
    try:
        current = cache.get(key) or 1
        cache.set(key, int(current) + 1, timeout=None)
    except Exception:
        try:
            cache.set(key, 2, timeout=None)
        except Exception:
            pass


def bump_home_cache() -> None:
    """Invalide le cache HTML de la page d’accueil (toutes les variantes)."""
    _bump_cache_version(HOME_CACHE_VERSION_KEY)
    # Best-effort : purge aussi d’éventuelles clés cache_page héritées
    for key in (
        "views.decorators.cache.cache_page..GET.00000000",
        "views.decorators.cache.cache_header..00000000",
    ):
        try:
            cache.delete(key)
        except Exception:
            pass


def bump_concerts_cache() -> None:
    """Invalide le cache HTML des pages concerts (liste + fiche)."""
    _bump_cache_version(CONCERTS_CACHE_VERSION_KEY)


def bump_public_events_cache() -> None:
    """Accueil + agenda concerts après changement GPS / lieu public."""
    bump_home_cache()
    bump_concerts_cache()


def home_cache_version() -> str:
    try:
        return str(cache.get(HOME_CACHE_VERSION_KEY) or 1)
    except Exception:
        return "1"


def concerts_cache_version() -> str:
    try:
        return str(cache.get(CONCERTS_CACHE_VERSION_KEY) or 1)
    except Exception:
        return "1"


def youtube_video_id(url: str) -> str:
    """Extrait l’id YouTube depuis une URL ou un id brut."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if YT_ID_RE.match(raw):
        return raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host in {"youtu.be", "www.youtu.be"}:
        vid = parsed.path.lstrip("/").split("/")[0]
        return vid if YT_ID_RE.match(vid) else ""
    if "youtube" in host:
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            vid = qs["v"][0]
            return vid if YT_ID_RE.match(vid) else ""
        parts = [p for p in parsed.path.split("/") if p]
        if parts and parts[0] in {"embed", "shorts", "live", "v"} and len(parts) > 1:
            vid = parts[1]
            return vid if YT_ID_RE.match(vid) else ""
    return ""


def youtube_embed_url(url: str) -> str:
    vid = youtube_video_id(url)
    if not vid:
        return ""
    return f"https://www.youtube-nocookie.com/embed/{vid}?rel=0"


def youtube_thumb_url(url: str) -> str:
    vid = youtube_video_id(url)
    if not vid:
        return ""
    return f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg"


def plain_text_to_html(text: str) -> str:
    """Convertit du texte multi-paragraphes en HTML sûr (fallback)."""
    raw = (text or "").strip()
    if not raw:
        return ""
    return linebreaks(escape(raw))


_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_MD_CODE_RE = re.compile(r"`([^`]+)`")
_SAFE_HREF_RE = re.compile(r"^(https?://|/|#mailto:)", re.I)


def _safe_href(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    # mailto: links written as mailto:… without # prefix
    if u.lower().startswith("mailto:") and "@" in u:
        return escape(u)
    if _SAFE_HREF_RE.match(u) or u.startswith("/"):
        return escape(u)
    return ""


def _inline_markdown(escaped_line: str) -> str:
    """Applique gras / italique / code / liens sur une ligne déjà échappée."""

    def link_sub(m):
        label, href = m.group(1), m.group(2)
        safe = _safe_href(href)
        if not safe:
            return m.group(0)
        return f'<a href="{safe}">{label}</a>'

    def bold_sub(m):
        return f"<strong>{m.group(1) or m.group(2)}</strong>"

    def italic_sub(m):
        return f"<em>{m.group(1) or m.group(2)}</em>"

    def code_sub(m):
        return f"<code>{m.group(1)}</code>"

    out = _MD_CODE_RE.sub(code_sub, escaped_line)
    out = _MD_LINK_RE.sub(link_sub, out)
    out = _MD_BOLD_RE.sub(bold_sub, out)
    out = _MD_ITALIC_RE.sub(italic_sub, out)
    return out


def markdown_to_html(text: str) -> str:
    """Markdown minimal sûr : paragraphes, **gras**, *italique*, liens, listes, titres.

    Le HTML brut saisi est échappé ; seuls les marqueurs Markdown introduisent des balises.
    """
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return ""

    blocks: list[str] = []
    lines = raw.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        # Titres ## / ###
        if stripped.startswith("### "):
            blocks.append(f"<h4>{_inline_markdown(escape(stripped[4:]))}</h4>")
            i += 1
            continue
        if stripped.startswith("## "):
            blocks.append(f"<h3>{_inline_markdown(escape(stripped[3:]))}</h3>")
            i += 1
            continue

        # Liste à puces (-, *, •)
        if re.match(r"^[-*•]\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"^[-*•]\s+", lines[i].strip()):
                item = re.sub(r"^[-*•]\s+", "", lines[i].strip())
                items.append(f"<li>{_inline_markdown(escape(item))}</li>")
                i += 1
            blocks.append("<ul>" + "".join(items) + "</ul>")
            continue

        # Citations « > texte » (comme le chat)
        if stripped.startswith(">"):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                item = re.sub(r"^>\s?", "", lines[i].strip())
                quote_lines.append(_inline_markdown(escape(item)))
                i += 1
            blocks.append(
                '<blockquote class="md-cite">'
                + "<br>\n".join(quote_lines)
                + "</blockquote>"
            )
            continue

        # Paragraphe (lignes non vides jusqu’à blanc)
        para_lines = []
        while i < len(lines) and lines[i].strip():
            # Stop before a list, quote or heading starting a new block
            s = lines[i].strip()
            if para_lines and (
                re.match(r"^[-*•]\s+", s)
                or s.startswith(">")
                or s.startswith("## ")
                or s.startswith("### ")
            ):
                break
            para_lines.append(escape(lines[i].rstrip()))
            i += 1
        inner = "<br>\n".join(_inline_markdown(pl) for pl in para_lines)
        blocks.append(f"<p>{inner}</p>")

    return "\n".join(blocks)


def block_image_url(block: PageBlock) -> str:
    data = block.contenu or {}
    if block.media_id:
        url = block.media.url_affichage
        if url:
            return url
        if block.media.fichier_actif:
            return block.media.fichier_actif.url
    return (data.get("image_url") or data.get("url") or "").strip()


def enrich_block(block: PageBlock) -> PageBlock:
    """Attache des attributs de rendu sur l’instance (non persistés)."""
    data = block.contenu or {}
    block.render = {
        "titre": data.get("titre") or data.get("title") or "",
        "tag": data.get("tag") or "",
        "subtitle": data.get("subtitle") or data.get("sous_titre") or "",
        "title_accent": data.get("title_accent") or "",
        "title": data.get("title") or data.get("titre_ligne") or "",
        "body_html": markdown_to_html(data.get("body") or data.get("texte") or ""),
        "cta_label": data.get("cta_label") or "",
        "cta_url": data.get("cta_url") or "",
        "image_url": block_image_url(block),
        "image_alt": data.get("image_alt") or data.get("alt") or "",
        "image_static": data.get("image_static") or "",
        "caption": data.get("caption") or data.get("legende") or "",
        "video_url": data.get("video_url") or data.get("url_externe") or "",
        "video_embed": youtube_embed_url(
            data.get("video_url") or data.get("url_externe") or ""
        ),
        "video_thumb": youtube_thumb_url(
            data.get("video_url") or data.get("url_externe") or ""
        ),
        "limit": int(data.get("limit") or data.get("limite") or 3),
    }
    if block.media_id and block.media and block.media.url_externe and block.type == PageBlock.TYPE_VIDEO:
        if not block.render["video_embed"]:
            block.render["video_url"] = block.media.url_externe
            block.render["video_embed"] = youtube_embed_url(block.media.url_externe)
            block.render["video_thumb"] = youtube_thumb_url(block.media.url_externe)
    return block


def get_published_page(slug: str) -> SitePage | None:
    try:
        return (
            SitePage.objects.filter(slug=slug, publie=True)
            .prefetch_related(
                Prefetch(
                    "blocks",
                    queryset=PageBlock.objects.filter(visible=True)
                    .select_related("media")
                    .order_by("ordre", "id"),
                )
            )
            .first()
        )
    except (ProgrammingError, OperationalError):
        return None


def serialize_block(block: PageBlock) -> dict[str, Any]:
    media_info = None
    if block.media_id and block.media:
        media_info = {
            "id": block.media_id,
            "titre": block.media.titre,
            "type": block.media.type,
            "url": block.media.url_affichage or (
                block.media.fichier_actif.url if block.media.fichier_actif else ""
            ),
            "url_externe": block.media.url_externe or "",
        }
    return {
        "id": block.pk,
        "type": block.type,
        "type_label": block.get_type_display(),
        "titre_admin": block.titre_admin or "",
        "label": block.label_carte(),
        "ordre": block.ordre,
        "visible": block.visible,
        "contenu": block.contenu or {},
        "media_id": block.media_id,
        "media": media_info,
    }


def default_contenu(block_type: str) -> dict[str, Any]:
    if block_type == PageBlock.TYPE_HERO:
        return {
            "title_accent": "J.O.Y",
            "title": "Jazz Orchestra Yonnais",
            "tag": "Big Band · La Roche-sur-Yon",
            "subtitle": "",
            "image_alt": "",
            "image_static": "",
            "image_url": "",
            "video_url": "",
        }
    if block_type == PageBlock.TYPE_TEXT:
        return {
            "titre": "Nouveau texte",
            "body": "",
            "cta_label": "",
            "cta_url": "",
        }
    if block_type == PageBlock.TYPE_IMAGE:
        return {"image_alt": "", "caption": "", "image_url": ""}
    if block_type == PageBlock.TYPE_VIDEO:
        return {"titre": "", "video_url": ""}
    if block_type == PageBlock.TYPE_CONCERTS:
        return {"titre": "Prochains concerts", "limit": 3}
    return {}
