"""Génération d'images Open Graph (1200×630) style carte concert."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from django.conf import settings
from django.utils import timezone as dj_tz
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

OG_WIDTH = 1200
OG_HEIGHT = 630

BG = (245, 242, 236)  # --bg
SURFACE = (250, 248, 244)  # --surface
TEXT = (26, 23, 20)  # --text
MUTED = (107, 101, 96)  # --muted
ACCENT = (201, 79, 58)  # --accent
GOLD_TEXT = (138, 106, 26)  # --gold-text
ANNULE = (180, 60, 60)
BORDER = (230, 226, 218)

MONTHS_FR = (
    "",
    "JANV",
    "FÉVR",
    "MARS",
    "AVR",
    "MAI",
    "JUIN",
    "JUIL",
    "AOÛT",
    "SEPT",
    "OCT",
    "NOV",
    "DÉC",
)

_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
)
_FONT_BODY_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
)

_LOGO_CANDIDATES = (
    Path("/srv/jazz-orchestra-yonnais/data/logo-joy.webp"),
    Path(settings.BASE_DIR) / "users" / "static" / "users" / "icons" / "logo-joy.webp",
    Path(settings.BASE_DIR) / "users" / "static" / "users" / "icons" / "icon-192.png",
)


def _cache_dir() -> Path:
    path = Path(settings.MEDIA_ROOT) / "concert_og"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_path_for_slug(slug: str) -> Path:
    safe = "".join(c for c in slug if c.isalnum() or c in "-_")[:200] or "concert"
    return _cache_dir() / f"{safe}.jpg"


def content_fingerprint(event) -> str:
    """Hash des champs affichés sur l'image (invalidation sans updated_at)."""
    debut = dj_tz.localtime(event.date_debut) if event.date_debut else None
    parts = [
        "og-v2-concert",  # bump layout (mention CONCERT)
        event.slug or "",
        event.titre or "",
        event.statut or "",
        debut.isoformat() if debut else "",
        event.lieu_affiche or "",
        event.horaires_affiches or "",
        (event.organisme or "").strip(),
        str(event.parent_id or ""),
    ]
    if event.parent_id and getattr(event, "parent", None):
        parts.append(event.parent.titre or "")
    raw = "\n".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def invalidate_og_cache(slug: str | None) -> None:
    if not slug:
        return
    path = cache_path_for_slug(slug)
    meta = path.with_suffix(".sha")
    for p in (path, meta):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            logger.warning("Impossible de supprimer le cache OG %s", p, exc_info=True)


def _load_font(candidates: tuple[Path, ...], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in candidates:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _logo_image(size: int = 96) -> Image.Image | None:
    for path in _LOGO_CANDIDATES:
        if not path.is_file():
            continue
        try:
            im = Image.open(path).convert("RGBA")
            im.thumbnail((size, size), Image.LANCZOS)
            return im
        except OSError:
            continue
    return None


def render_concert_og(event) -> Image.Image:
    """Construit l'image 1200×630 (RGB) pour un Event."""
    img = Image.new("RGB", (OG_WIDTH, OG_HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # Panneau surface avec bordure légère
    margin = 48
    draw.rounded_rectangle(
        [margin, margin, OG_WIDTH - margin, OG_HEIGHT - margin],
        radius=12,
        fill=SURFACE,
        outline=BORDER,
        width=2,
    )

    font_brand = _load_font(_FONT_BODY_CANDIDATES, 28)
    font_label = _load_font(_FONT_BODY_CANDIDATES, 22)
    font_day = _load_font(_FONT_CANDIDATES, 140)
    font_month = _load_font(_FONT_BODY_CANDIDATES, 28)
    font_title = _load_font(_FONT_CANDIDATES, 52)
    font_meta = _load_font(_FONT_BODY_CANDIDATES, 30)
    font_badge = _load_font(_FONT_BODY_CANDIDATES, 22)

    left = margin + 56
    top = margin + 40
    right = OG_WIDTH - margin - 56

    logo = _logo_image(72)
    brand_x = left
    if logo is not None:
        img.paste(logo, (left, top), logo)
        brand_x = left + logo.width + 20
    draw.text((brand_x, top + 18), "Jazz Orchestra Yonnais", font=font_brand, fill=MUTED)

    # Mention CONCERT (coin haut droit)
    label = "CONCERT"
    label_w = draw.textlength(label, font=font_label)
    label_x = right - label_w
    label_y = top + 22
    pad_x, pad_y = 14, 8
    draw.rounded_rectangle(
        [
            label_x - pad_x,
            label_y - pad_y,
            right + pad_x,
            label_y + 22 + pad_y,
        ],
        radius=4,
        fill=ACCENT,
    )
    draw.text((label_x, label_y), label, font=font_label, fill=(255, 255, 255))

    debut = dj_tz.localtime(event.date_debut)
    day = f"{debut.day:02d}"
    month_line = f"{MONTHS_FR[debut.month]} {debut.year}"

    date_x = left
    date_y = top + 110
    draw.text((date_x, date_y), day, font=font_day, fill=ACCENT)
    day_box = draw.textbbox((date_x, date_y), day, font=font_day)
    month_x = day_box[2] + 28
    month_y = date_y + 48
    draw.text((month_x, month_y), month_line, font=font_month, fill=MUTED)

    content_x = left
    content_y = day_box[3] + 28
    max_text_w = OG_WIDTH - margin * 2 - 112

    title_lines = _wrap_text(draw, event.titre or "Concert", font_title, max_text_w)[:3]
    for line in title_lines:
        draw.text((content_x, content_y), line, font=font_title, fill=TEXT)
        content_y += 62

    if event.statut == "tentative":
        badge = "DATE À CONFIRMER"
        badge_color = GOLD_TEXT
    elif event.statut == "annule":
        badge = "ANNULÉ"
        badge_color = ANNULE
    else:
        badge = None
        badge_color = MUTED

    if badge:
        content_y += 8
        draw.text((content_x, content_y), badge, font=font_badge, fill=badge_color)
        content_y += 36

    meta_parts = []
    if event.parent_id and getattr(event, "parent", None) and event.parent.titre:
        meta_parts.append(f"Dans : {event.parent.titre}")
    if (event.organisme or "").strip():
        meta_parts.append(f"Organisé par {event.organisme.strip()}")
    lieu = event.lieu_affiche or ""
    horaires = event.horaires_affiches or ""
    if lieu and horaires:
        meta_parts.append(f"{lieu} · {horaires}")
    elif lieu:
        meta_parts.append(lieu)
    elif horaires:
        meta_parts.append(horaires)

    content_y += 12
    for part in meta_parts:
        for line in _wrap_text(draw, part, font_meta, max_text_w)[:2]:
            draw.text((content_x, content_y), line, font=font_meta, fill=MUTED)
            content_y += 40
            if content_y > OG_HEIGHT - margin - 40:
                break

    # Accent bar en bas
    draw.rectangle(
        [margin, OG_HEIGHT - margin - 8, OG_WIDTH - margin, OG_HEIGHT - margin],
        fill=ACCENT,
    )
    return img


def get_or_create_og_image(event) -> Path:
    """Retourne le chemin du JPEG en cache, (re)généré si besoin."""
    path = cache_path_for_slug(event.slug)
    meta = path.with_suffix(".sha")
    fp = content_fingerprint(event)
    if path.is_file() and meta.is_file():
        try:
            if meta.read_text(encoding="utf-8").strip() == fp:
                return path
        except OSError:
            pass

    image = render_concert_og(event)
    tmp = path.with_suffix(".tmp.jpg")
    image.save(tmp, "JPEG", quality=85, optimize=True)
    tmp.replace(path)
    meta.write_text(fp, encoding="utf-8")
    return path
