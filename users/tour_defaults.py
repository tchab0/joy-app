"""Étapes par défaut des guides musicien / staff (IA Coulisses)."""

MUSICIAN_STEPS = [
    {
        "order": 1,
        "anchor": "",
        "title": "Bienvenue",
        "body": (
            "Ce guide présente les Coulisses : planning, partitions et chat, "
            "puis votre compte. Vous pourrez le rejouer depuis "
            "Mon compte → Réglages."
        ),
        "page_path": "/planning/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 2,
        "anchor": "nav-coulisses",
        "title": "Coulisses",
        "body": (
            "Une seule entrée dans le menu pour tout l’espace musicien. "
            "À l’intérieur : Planning, Répertoire et Chat."
        ),
        "page_path": "/planning/",
        "open_mobile_nav": True,
        "scroll_footer": False,
    },
    {
        "order": 3,
        "anchor": "module-calendrier",
        "title": "Calendrier",
        "body": (
            "Vue annuelle des dates. Touchez un jour pour le détail, "
            "ou proposez un événement si vous y êtes autorisé."
        ),
        "page_path": "/planning/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 4,
        "anchor": "module-mes-dates",
        "title": "Mes dates",
        "body": (
            "Vos invitations, sondages et remplacements sont regroupés ici."
        ),
        "page_path": "/planning/moi/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 5,
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
        "order": 6,
        "anchor": "module-repertoire",
        "title": "Morceaux",
        "body": (
            "Le répertoire se trouve dans Coulisses → Morceaux "
            "(plus dans un menu séparé en haut du site)."
        ),
        "page_path": "/repertoire/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 7,
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
        "order": 8,
        "anchor": "module-chat",
        "title": "Salons",
        "body": (
            "Le chat est aussi dans les Coulisses. "
            "Salons orchestre, par morceau ou par date."
        ),
        "page_path": "/chat/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 9,
        "anchor": "chat-list",
        "title": "Liste des salons",
        "body": (
            "Ouvrez un salon pour discuter et recevoir les documents. "
            "Les notifications se règlent sous Mon compte."
        ),
        "page_path": "/chat/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 10,
        "anchor": "nav-account",
        "title": "Mon compte",
        "body": (
            "Sécurité, notifications et réglages — hors des Coulisses, "
            "dans le menu principal."
        ),
        "page_path": "/compte/",
        "open_mobile_nav": True,
        "scroll_footer": False,
    },
    {
        "order": 11,
        "anchor": "account-replay",
        "title": "C’est tout !",
        "body": (
            "Relancez ce guide à tout moment depuis Mon compte → Réglages."
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
        "title": "Guide staff",
        "body": (
            "En plus du guide musicien, ce parcours montre les outils "
            "d’organisation : groupe Staff dans les Coulisses, puis le "
            "tableau de bord Administration. Rejouable depuis Mon compte."
        ),
        "page_path": "/planning/admin/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 2,
        "anchor": "module-staff",
        "title": "Groupe Staff",
        "body": (
            "Dans Coulisses, le bloc Staff regroupe le quotidien orchestre : "
            "admin planning, musiciens, atelier et setlists "
            "(et Répés dans Planning)."
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
            "Créez et gérez les événements, effectifs (rosters), "
            "sondages de dates et matériel."
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
            "Profils, postes titulaires et remplaçants, accès planning."
        ),
        "page_path": "/planning/admin/musiciens/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 5,
        "anchor": "staff-repes",
        "title": "Répétitions",
        "body": (
            "Feuilles de route et absences : sous Planning → Répés "
            "(réservé au staff)."
        ),
        "page_path": "/repetitions/staff/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 6,
        "anchor": "staff-atelier",
        "title": "Atelier partitions",
        "body": (
            "Publiez les morceaux : PDF, découpe par poste, audio."
        ),
        "page_path": "/repertoire/staff/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 7,
        "anchor": "staff-setlists",
        "title": "Setlists",
        "body": (
            "Composez les programmes de concert à partir du répertoire."
        ),
        "page_path": "/repertoire/staff/setlists/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 8,
        "anchor": "footer-admin",
        "title": "Raccourcis Administration",
        "body": (
            "En bas de page : accès rapide au tableau de bord, retours, "
            "CMS concerts, planning et atelier."
        ),
        "page_path": "/repertoire/staff/setlists/",
        "open_mobile_nav": False,
        "scroll_footer": True,
    },
    {
        "order": 9,
        "anchor": "admin-hub",
        "title": "Tableau de bord",
        "body": (
            "Tous les outils staff au même endroit : site public "
            "(concerts, lieux, médias, contact), orchestre, retours, "
            "stats, édition des guides et Django admin."
        ),
        "page_path": "/administration/",
        "open_mobile_nav": False,
        "scroll_footer": False,
    },
    {
        "order": 10,
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
