"""Formatage du corps des notifications (markdown léger → HTML sûr)."""

from __future__ import annotations

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(name="notif_body_html")
def notif_body_html(text: str) -> str:
    """Rendu markdown minimal (liens, listes, gras) pour l’inbox."""
    from core.page_cms import markdown_to_html

    return mark_safe(markdown_to_html(text or ""))
