"""Ancres data-tour connues (cibles des bulles)."""

from __future__ import annotations

# Libellé court pour l’éditeur admin
TOUR_ANCHORS: list[tuple[str, str]] = [
    ("", "Plein écran (accueil / fin)"),
    ("nav-coulisses", "Nav — Coulisses"),
    ("nav-account", "Nav — Mon compte"),
    ("module-calendrier", "Coulisses — Calendrier"),
    ("module-mes-dates", "Coulisses — Mes dates"),
    ("module-repertoire", "Coulisses — Morceaux"),
    ("module-chat", "Coulisses — Salons"),
    ("module-staff", "Coulisses — Groupe Staff"),
    ("rsvp-actions", "Mes dates — Réponses RSVP"),
    ("repertoire-filter", "Répertoire — Filtre poste"),
    ("chat-list", "Chat — Liste des salons"),
    ("staff-admin", "Staff — Admin planning"),
    ("staff-musiciens", "Staff — Musiciens"),
    ("staff-repes", "Staff — Répétitions"),
    ("staff-atelier", "Staff — Atelier partitions"),
    ("staff-setlists", "Staff — Setlists"),
    ("footer-admin", "Pied de page — Administration"),
    ("admin-hub", "Tableau de bord Administration"),
    ("account-replay", "Compte — Rejouer le guide"),
]

TOUR_PAGE_PATHS: list[tuple[str, str]] = [
    ("", "Page courante (pas de navigation)"),
    ("/compte/", "Mon compte"),
    ("/planning/", "Calendrier"),
    ("/planning/moi/", "Mes dates"),
    ("/planning/admin/", "Admin planning"),
    ("/planning/admin/musiciens/", "Musiciens"),
    ("/repetitions/staff/", "Répétitions"),
    ("/repertoire/", "Morceaux"),
    ("/repertoire/staff/", "Atelier partitions"),
    ("/repertoire/staff/setlists/", "Setlists"),
    ("/chat/", "Chat"),
    ("/administration/", "Tableau de bord admin"),
]
