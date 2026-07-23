"""Étapes par défaut des guides musicien / staff."""

MUSICIAN_STEPS = [
    {
        "order": 1,
        "anchor": "",
        "title": "Bienvenue",
        "body": (
            "Ce guide présente les outils réservés aux musiciens : "
            "coulisses (planning et répertoire), chat et votre compte. "
            "Vous pourrez le rejouer depuis Mon compte → Réglages."
        ),
        "page_path": "/compte/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 2,
        "anchor": "nav-coulisses",
        "title": "Coulisses",
        "body": (
            "Dates, répétitions, concerts et répertoire : tout passe "
            "par ici. Le calendrier annuel s’affiche en premier ; "
            "les partitions sont dans l’onglet Morceaux."
        ),
        "page_path": "/compte/",
        "open_mobile_nav": True,
        "scroll_footer": False,
    },
    {
        "order": 3,
        "anchor": "nav-chat",
        "title": "Chat",
        "body": (
            "Échangez avec l’orchestre, par morceau ou par date, "
            "et recevez les documents partagés."
        ),
        "page_path": "/compte/",
        "open_mobile_nav": True,
        "scroll_footer": False,
    },
    {
        "order": 4,
        "anchor": "nav-account",
        "title": "Mon compte",
        "body": (
            "Profil, sécurité, notifications — et le bouton pour "
            "rejouer ce guide quand vous voulez."
        ),
        "page_path": "/compte/",
        "open_mobile_nav": True,
        "scroll_footer": False,
    },
    {
        "order": 5,
        "anchor": "module-calendrier",
        "title": "Calendrier",
        "body": (
            "Vue annuelle des dates. Touchez un jour pour voir le détail "
            "ou proposer un événement si vous y êtes autorisé."
        ),
        "page_path": "/planning/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 6,
        "anchor": "module-mes-dates",
        "title": "Mes dates",
        "body": (
            "Vos invitations, réponses (RSVP), remplacements et sondages "
            "de dates se retrouvent ici."
        ),
        "page_path": "/planning/moi/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 7,
        "anchor": "rsvp-actions",
        "title": "Répondre à une date",
        "body": (
            "Pour chaque invitation : Oui, Peut-être ou Non. "
            "Répondez dès que possible pour aider le staff."
        ),
        "page_path": "/planning/moi/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 8,
        "anchor": "repertoire-filter",
        "title": "Filtrer votre poste",
        "body": (
            "Choisissez votre poste pour n’afficher que vos parties, "
            "puis ouvrez le PDF ou la fiche du morceau."
        ),
        "page_path": "/repertoire/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 9,
        "anchor": "chat-list",
        "title": "Salons de discussion",
        "body": (
            "Liste des salons orchestre, morceaux et événements. "
            "Les préférences de notification sont sous Mon compte."
        ),
        "page_path": "/chat/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 10,
        "anchor": "account-replay",
        "title": "C’est tout !",
        "body": (
            "Vous pouvez relancer ce guide à tout moment depuis "
            "Mon compte → Réglages."
        ),
        "page_path": "/compte/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
]

STAFF_STEPS = [
    {
        "order": 1,
        "anchor": "",
        "title": "Guide administration",
        "body": (
            "Ce parcours présente les outils staff : module Coulisses, "
            "musiciens, atelier et liens d’administration en bas de page. "
            "Rejouable depuis Mon compte → Réglages."
        ),
        "page_path": "/compte/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 2,
        "anchor": "module-staff",
        "title": "Groupe Staff",
        "body": (
            "Dans Coulisses, le groupe Staff regroupe "
            "l’admin des dates, les musiciens, l’atelier et les setlists."
        ),
        "page_path": "/planning/admin/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 3,
        "anchor": "staff-admin",
        "title": "Admin planning",
        "body": (
            "Créez et gérez les événements, les effectifs (rosters), "
            "les sondages et le matériel."
        ),
        "page_path": "/planning/admin/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 4,
        "anchor": "staff-musiciens",
        "title": "Musiciens",
        "body": (
            "Gérez les profils musiciens : postes, pupitres et accès."
        ),
        "page_path": "/planning/admin/musiciens/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 5,
        "anchor": "staff-atelier",
        "title": "Atelier & setlists",
        "body": (
            "Publiez le répertoire (partitions, audio) et composez "
            "les setlists de concert."
        ),
        "page_path": "/repertoire/staff/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 6,
        "anchor": "footer-admin",
        "title": "Administration du site",
        "body": (
            "En bas de chaque page : concerts, lieux, médias, contact, "
            "retours utilisateurs et l’admin Django."
        ),
        "page_path": "/compte/",
        "open_mobile_nav": False,
        "scroll_footer": True,
    },
    {
        "order": 7,
        "anchor": "account-replay",
        "title": "Fin du guide staff",
        "body": (
            "Relancez ce guide depuis Mon compte → Réglages "
            "quand un nouvel outil arrive."
        ),
        "page_path": "/compte/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
]
