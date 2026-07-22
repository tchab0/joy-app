"""Aides / textes explicatifs en haut de page — masquage et restauration."""

from __future__ import annotations

from django.db import DatabaseError

# Clé → libellé Mon compte (ordre d’affichage).
PAGE_LEAD_LABELS: dict[str, str] = {
    "planning.dashboard": "Planning — mes dates",
    "planning.calendar": "Planning — calendrier",
    "planning.propose_event": "Proposer un événement",
    "planning.admin_dashboard": "Staff — tableau de bord",
    "planning.admin_musicians": "Staff — musiciens",
    "repertoire.pieces": "Répertoire — partitions",
    "repertoire.staff_pieces": "Staff — morceaux",
    "repertoire.staff_piece_form": "Staff — éditer un morceau",
    "repertoire.staff_piece_split": "Staff — découper un PDF",
    "repertoire.staff_setlists": "Staff — setlists",
    "repertoire.staff_setlist_form": "Staff — éditer une setlist",
    "repetitions.staff_list": "Staff — répétitions",
    "repetitions.staff_form": "Staff — fiche répétition",
    "chat.rooms": "Chat",
    "chat.prefs": "Notifications chat",
    "stats.dashboard": "Statistiques",
    "core.contact": "Contact",
    "core.adhesion": "Adhérer",
    "core.goodies": "Goodies",
    "core.proposer_media": "Proposer un média",
    "core.admin_contact": "Staff — messages contact",
    "users.security": "Sécurité",
    "users.member_area": "Espace adhérent",
    "feedback.admin": "Staff — retours utilisateurs",
}

KNOWN_PAGE_LEAD_KEYS = frozenset(PAGE_LEAD_LABELS)


def get_dismissed_page_leads(user) -> set[str]:
    if not user or not getattr(user, "is_authenticated", False):
        return set()
    try:
        raw = getattr(user, "dismissed_page_leads", None) or []
    except DatabaseError:
        return set()
    if not isinstance(raw, list):
        return set()
    return {str(k) for k in raw if k}


def dismiss_page_lead(user, key: str) -> bool:
    """Ajoute une clé aux aides masquées. Retourne False si clé inconnue."""
    key = (key or "").strip()
    if key not in KNOWN_PAGE_LEAD_KEYS:
        return False
    current = list(get_dismissed_page_leads(user))
    if key in current:
        return True
    current.append(key)
    try:
        user.dismissed_page_leads = current
        user.save(update_fields=["dismissed_page_leads"])
    except DatabaseError:
        return False
    return True


def restore_all_page_leads(user) -> int:
    """Réaffiche toutes les aides. Retourne le nombre qui étaient masquées."""
    dismissed = get_dismissed_page_leads(user)
    if not dismissed:
        return 0
    try:
        user.dismissed_page_leads = []
        user.save(update_fields=["dismissed_page_leads"])
    except DatabaseError:
        return 0
    return len(dismissed)


def dismissed_page_leads_for_account(user) -> list[tuple[str, str]]:
    """Liste (clé, libellé) des aides masquées, pour Mon compte."""
    dismissed = get_dismissed_page_leads(user)
    return [
        (key, label)
        for key, label in PAGE_LEAD_LABELS.items()
        if key in dismissed
    ]
