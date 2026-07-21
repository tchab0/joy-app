"""Helpers pour l’ordre des solos / chorus (parse, format, pool musiciens)."""

from __future__ import annotations

import re
import unicodedata

from planning.models import MusicianProfile

_NUM_PREFIX = re.compile(r"^\d+[\.\)]\s*")
_INLINE_SPLIT = re.compile(r"\s+(?=\d+[\.\)]\s)")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").strip().lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text)


def parse_chorus_order(text: str) -> list[str]:
    """Découpe un texte d’ordre de chorus en libellés (sans numéros)."""
    text = (text or "").strip()
    if not text:
        return []
    labels: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        chunks = _INLINE_SPLIT.split(line) if _INLINE_SPLIT.search(line) else [line]
        for chunk in chunks:
            label = _NUM_PREFIX.sub("", chunk.strip()).strip()
            if label:
                labels.append(label)
    return labels


def format_chorus_order(labels: list[str]) -> str:
    """Formate une liste ordonnée en texte numéroté (1. …)."""
    clean = [(t or "").strip() for t in labels if (t or "").strip()]
    return "\n".join(f"{i}. {label}" for i, label in enumerate(clean, 1))


def solo_pool_entries() -> list[dict]:
    """
    Entrées glissables : un titulaire par poste, sinon le poste nu.

    Chaque entrée : {id, title, name, poste}.
    """
    titulaires = (
        MusicianProfile.objects.filter(
            user__is_musician=True,
            poste_titulaire__gt="",
        )
        .select_related("user")
        .order_by("user__last_name", "user__first_name", "pk")
    )
    by_poste: dict[str, list[MusicianProfile]] = {}
    for profile in titulaires:
        by_poste.setdefault(profile.poste_titulaire, []).append(profile)

    pool: list[dict] = []
    for value, label in MusicianProfile.Poste.choices:
        holders = by_poste.get(value) or []
        if holders:
            for profile in holders:
                name = str(profile.user)
                pool.append(
                    {
                        "id": f"m{profile.pk}",
                        "name": name,
                        "poste": label,
                        "title": f"{name} — {label}",
                    }
                )
        else:
            pool.append(
                {
                    "id": f"p:{value}",
                    "name": "",
                    "poste": label,
                    "title": label,
                }
            )
    return pool


def resolve_solo_selection(
    chorus_text: str,
    pool: list[dict] | None = None,
) -> list[dict]:
    """
    Reconstitue la sélection ordonnée depuis le texte stocké.

    Correspondance exacte sur title / poste / name, sinon entrée custom.
    """
    pool = pool if pool is not None else solo_pool_entries()
    by_norm_title = {_norm(p["title"]): p for p in pool}
    by_norm_poste = {_norm(p["poste"]): p for p in pool if p.get("poste")}
    by_norm_name = {_norm(p["name"]): p for p in pool if p.get("name")}

    selected: list[dict] = []
    used: set[str] = set()
    for i, label in enumerate(parse_chorus_order(chorus_text)):
        key = _norm(label)
        match = by_norm_title.get(key)
        if match is None:
            match = by_norm_poste.get(key)
        if match is None:
            match = by_norm_name.get(key)
        if match is not None and match["id"] not in used:
            selected.append(dict(match))
            used.add(match["id"])
            continue
        selected.append(
            {
                "id": f"custom-{i}",
                "name": label,
                "poste": "",
                "title": label,
            }
        )
    return selected


def solo_builder_context(chorus_order: str = "") -> dict:
    pool = solo_pool_entries()
    return {
        "solo_pool": pool,
        "solo_selected": resolve_solo_selection(chorus_order, pool),
    }
