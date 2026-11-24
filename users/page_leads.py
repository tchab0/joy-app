"""Aides / textes explicatifs en haut de page — masquage et restauration.

Les clés ``feature.*`` sont des annonces one-shot (popup) : elles partagent
le stockage ``dismissed_page_leads`` mais ne sont pas restaurées avec les
textes d’aide de page.
"""

from __future__ import annotations

from django.db import DatabaseError
from django.urls import reverse

from users.roles import user_can_access_planning

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
    "repetitions.detail": "Répétition — setlist & demandes",
    "chat.rooms": "Chat",
    "chat.prefs": "Préférences de notifications",
    "stats.dashboard": "Statistiques",
    "core.contact": "Contact",
    "core.adhesion": "Adhérer",
    "core.goodies": "Goodies",
    "core.proposer_media": "Proposer un média",
    "core.admin_contact": "Staff — messages contact",
    "core.admin_notifications": "Staff — notifications musiciens",
    "core.admin_hub": "Staff — tableau de bord",
    "core.admin_presentation": "Staff — présentation du site",
    "users.security": "Sécurité",
    "users.member_area": "Espace adhérent",
    "feedback.admin": "Staff — retours utilisateurs",
    "users.admin_tours": "Staff — guides d’aide",
}

# Annonces fonctionnelles (popup une fois) — hors restauration « textes d’aide ».
FEATURE_ANNOUNCE_LABELS: dict[str, str] = {
    "feature.calendar_sync": "Synchro agenda perso",
}

FEATURE_ANNOUNCE_ORDER: tuple[str, ...] = ("feature.calendar_sync",)

KNOWN_PAGE_LEAD_KEYS = frozenset(PAGE_LEAD_LABELS)
KNOWN_FEATURE_ANNOUNCE_KEYS = frozenset(FEATURE_ANNOUNCE_LABELS)
KNOWN_DISMISS_KEYS = KNOWN_PAGE_LEAD_KEYS | KNOWN_FEATURE_ANNOUNCE_KEYS


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
    """Ajoute une clé (aide de page ou annonce feature). Retourne False si inconnue."""
    key = (key or "").strip()
    if key not in KNOWN_DISMISS_KEYS:
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
    """Réaffiche les aides de page (pas les annonces feature.*)."""
    dismissed = get_dismissed_page_leads(user)
    page_only = {k for k in dismissed if k in KNOWN_PAGE_LEAD_KEYS}
    if not page_only:
        return 0
    keep = [k for k in dismissed if k not in KNOWN_PAGE_LEAD_KEYS]
    try:
        user.dismissed_page_leads = keep
        user.save(update_fields=["dismissed_page_leads"])
    except DatabaseError:
        return 0
    return len(page_only)


def dismissed_page_leads_for_account(user) -> list[tuple[str, str]]:
    """Liste (clé, libellé) des aides masquées, pour Mon compte."""
    dismissed = get_dismissed_page_leads(user)
    return [
        (key, label)
        for key, label in PAGE_LEAD_LABELS.items()
        if key in dismissed
    ]


def _calendar_sync_announce_payload() -> dict:
    return {
        "key": "feature.calendar_sync",
        "title": "Nouveau : synchro avec votre agenda",
        "intro": (
            "Vous pouvez maintenant abonner Google Agenda, Apple ou Outlook "
            "aux dates JOY. Les concerts confirmés s’ajoutent tout seuls "
            "(sans les répétitions)."
        ),
        "steps": [
            {
                "title": "Ouvrir Mon compte",
                "body": "Allez dans Mon compte → bloc « Agenda perso » (lien aussi depuis le calendrier).",
            },
            {
                "title": "Choisir un flux",
                "body": (
                    "Orchestre = toutes les dates confirmées. "
                    "Mes dates = seulement celles où vous êtes invité·e, « peut-être » ou dispo."
                ),
            },
            {
                "title": "S’abonner",
                "body": (
                    "Sur mobile : bouton « S’abonner (webcal) ». "
                    "Sur Google Agenda (ordinateur) : Autres agendas → + → À partir de l’URL → coller l’URL."
                ),
            },
        ],
        "cta_label": "Voir Agenda perso",
        "cta_url": f"{reverse('account_home')}#agenda-perso",
        "dismiss_label": "Compris",
    }


_FEATURE_ANNOUNCE_BUILDERS = {
    "feature.calendar_sync": _calendar_sync_announce_payload,
}


def pending_feature_announce(user) -> dict | None:
    """Prochaine annonce feature à afficher (musiciens, hors mdp provisoire)."""
    if not user or not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "must_change_password", False):
        return None
    if not user_can_access_planning(user):
        return None
    dismissed = get_dismissed_page_leads(user)
    for key in FEATURE_ANNOUNCE_ORDER:
        if key in dismissed:
            continue
        builder = _FEATURE_ANNOUNCE_BUILDERS.get(key)
        if builder is None:
            continue
        try:
            return builder()
        except Exception:
            return None
    return None
