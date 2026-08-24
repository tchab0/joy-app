"""Organismes mémorisés (nom + site web) liés au champ texte Event.organisme."""

from __future__ import annotations

from .models import Organisme


def organisme_url_for_name(nom: str) -> str:
    nom = (nom or "").strip()
    if not nom:
        return ""
    obj = Organisme.objects.filter(nom__iexact=nom).first()
    return (obj.url_site or "").strip() if obj else ""


def remember_organisme(name: str, url_site: str = "") -> str:
    """Mémorise un organisme saisi (typeahead) et renvoie le nom normalisé."""
    nom = (name or "").strip()[:200]
    if not nom:
        return ""
    url = (url_site or "").strip()
    obj, _ = Organisme.objects.get_or_create(nom=nom)
    if obj.url_site != url:
        obj.url_site = url
        obj.save(update_fields=["url_site"])
    return nom
