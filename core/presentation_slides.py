"""Contenu du diaporama de présentation JOY (staff → Suivi & système)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PresentationSlide:
    id: str
    title: str
    summary: str
    steps: list[str] = field(default_factory=list)
    section: str = ""  # libellé de chapitre (slide de séparation si non vide + is_section)
    is_section: bool = False
    url_name: str = ""
    url_kwargs: dict | None = None
    url_path: str = ""  # chemin brut si pas de name Django
    demo_label: str = "Ouvrir la page en direct"


SLIDES: list[PresentationSlide] = [
    # ── Introduction ──────────────────────────────────────────────
    PresentationSlide(
        id="intro",
        title="JOY — Jazz Orchestra Yonnais",
        summary=(
            "Ce diaporama vous guide pour présenter le site aux musiciens. "
            "Chaque diapo décrit une fonctionnalité et la procédure à suivre. "
            "Utilisez le bouton « Ouvrir en direct » pour montrer la vraie page."
        ),
        steps=[
            "Flèches ← → ou boutons en bas pour naviguer",
            "Touche F : plein écran (idéal pour vidéoprojecteur)",
            "Touche Échap : quitter le plein écran",
            "Diapo suivante : pourquoi une app comme celle-ci plutôt qu’un groupe WhatsApp",
            "Puis le site public, et enfin les Coulisses musicien",
        ],
        is_section=True,
        section="Introduction",
    ),
    PresentationSlide(
        id="intro-pourquoi",
        title="Pourquoi cette app ?",
        summary=(
            "JOY est une application web conçue pour l’orchestre : "
            "pas d’installation, accessible partout, et bien plus qu’une messagerie."
        ),
        steps=[
            "Aucune installation : ouvrir le site dans le navigateur (téléphone, tablette ou ordinateur). "
            "Pas de téléchargement App Store / Play Store, pas de mise à jour à gérer manuellement",
            "Un seul endroit : planning, partitions, chat, feuilles de route et notifications — "
            "fini les infos éparpillées entre plusieurs groupes WhatsApp, emails et fichiers Drive",
            "Mieux qu’une messagerie seule : calendrier partagé, réponses oui/non aux invitations, "
            "sondages de disponibilités, partitions PDF filtrées par instrument, feuilles de route par événement",
            "Mieux qu’une app achetée ou standard (PlanningPME, BandHelper, etc.) : "
            "outil sur mesure pour JOY, sans abonnement mensuel à un éditeur tiers, "
            "données hébergées chez nous, évolutif selon vos retours",
            "Sur ordinateur comme sur mobile : même compte, même contenu — pratique en répétition "
            "sur le téléphone et à la maison sur un grand écran",
        ],
    ),
    # ── Site public ───────────────────────────────────────────────
    PresentationSlide(
        id="sec-public",
        title="Le site public",
        summary="Pages accessibles à tous, sans connexion — vitrine de l'orchestre.",
        is_section=True,
        section="Site public",
    ),
    PresentationSlide(
        id="public-home",
        title="Page d'accueil",
        summary="Première impression du site : actualités, prochains concerts, contenu éditorial.",
        steps=[
            "Ouvrez la page d'accueil depuis le menu « Accueil » ou le logo JOY",
            "Faites défiler : blocs texte, photos, liens vers les concerts à venir",
            "Montrez que le site est responsive (téléphone et ordinateur)",
        ],
        url_name="home",
        demo_label="Ouvrir l'accueil",
    ),
    PresentationSlide(
        id="public-concerts",
        title="Agenda des concerts",
        summary="Liste des concerts publics à venir et récents, avec fiche détaillée par événement.",
        steps=[
            "Menu → « Concerts »",
            "Cliquez sur un concert pour voir lieu, date, carte, météo et partage",
            "La fiche concert est partageable (lien, image Open Graph pour les réseaux)",
        ],
        url_name="concerts",
        demo_label="Ouvrir la liste des concerts",
    ),
    PresentationSlide(
        id="public-medias",
        title="Médiathèque",
        summary="Photos, vidéos et enregistrements audio publiés par l'orchestre.",
        steps=[
            "Menu → « Médias »",
            "Parcourez les albums par événement ou les photos « Préférées »",
            "Cliquez sur une photo pour l'agrandir ; bouton « ▶ Diaporama » pour un défilement automatique",
            "Les visiteurs peuvent voter pour leurs photos préférées (sans compte)",
        ],
        url_name="medias",
        demo_label="Ouvrir la médiathèque",
    ),
    PresentationSlide(
        id="public-proposer-media",
        title="Proposer un média",
        summary="Tout le monde peut envoyer photos ou fichiers pour publication après modération.",
        steps=[
            "Depuis « Médias », cliquez sur « Proposer un média »",
            "Remplissez le formulaire : fichier, titre, événement concerné (si connu)",
            "Envoyez — le staff valide avant publication",
        ],
        url_name="proposer_media",
        demo_label="Ouvrir le formulaire de proposition",
    ),
    PresentationSlide(
        id="public-contact",
        title="Contact & prestations",
        summary="Formulaire de contact général et demande de prestation (mariage, événement…).",
        steps=[
            "Menu → « Contact »",
            "Formulaire classique : nom, email, message",
            "Pour une prestation : choisir le mode « Prestation » (date, lieu, type d'événement)",
            "Les messages arrivent au staff dans l'administration",
        ],
        url_name="contact",
        demo_label="Ouvrir le contact",
    ),
    PresentationSlide(
        id="public-prestations",
        title="Page Prestations",
        summary="Présentation des offres de l'orchestre pour les organisateurs d'événements.",
        steps=[
            "Menu → « Prestations » (ou lien depuis Contact)",
            "Lisez la présentation des formules",
            "Le bouton mène vers le formulaire de demande de devis",
        ],
        url_name="prestations",
        demo_label="Ouvrir Prestations",
    ),
    PresentationSlide(
        id="public-login",
        title="Connexion",
        summary="Point d'entrée pour musiciens et adhérents. Plusieurs modes de connexion sécurisés.",
        steps=[
            "Menu → « Connexion » (ou « Mon compte » si déjà connecté)",
            "Option 1 : email + mot de passe",
            "Option 2 : code à usage unique envoyé par email ou SMS (sans mot de passe)",
            "Si la double authentification est activée : saisir le code TOTP ou reçu par email/SMS",
        ],
        url_path="/compte/connexion/",
        demo_label="Ouvrir la page de connexion",
    ),
    # ── Coulisses musicien ────────────────────────────────────────
    PresentationSlide(
        id="sec-musician",
        title="Les Coulisses — espace musicien",
        summary=(
            "Réservé aux musiciens connectés (rôle « musicien »). "
            "Le menu « Coulisses » apparaît après connexion."
        ),
        is_section=True,
        section="Coulisses musicien",
        url_name="planning:dashboard",
        demo_label="Ouvrir les Coulisses",
    ),
    PresentationSlide(
        id="mus-nav",
        title="Navigation Coulisses",
        summary="Sous-menu commun à toutes les sections réservées aux musiciens.",
        steps=[
            "Après connexion, cliquez sur « Coulisses » dans le menu principal",
            "Sous-navigation : Planning · Répertoire · Chat · (Répétitions selon contexte)",
            "Sur mobile : menu hamburger puis Coulisses",
            "Le pied de page reste accessible ; le contenu critique est utilisable au doigt",
        ],
        url_name="planning:dashboard",
        demo_label="Ouvrir le planning (Coulisses)",
    ),
    PresentationSlide(
        id="mus-compte",
        title="Mon compte",
        summary="Hub personnel : rôles, préférences, retours envoyés, relance des guides d'aide.",
        steps=[
            "Menu → « Mon compte » (ou avatar / lien compte)",
            "Consultez vos rôles (musicien, adhérent…)",
            "Relancez un guide interactif si besoin",
            "Voir l'historique de vos retours (bugs, suggestions) et répondre au staff",
        ],
        url_path="/compte/",
        demo_label="Ouvrir Mon compte",
    ),
    PresentationSlide(
        id="mus-securite",
        title="Sécurité du compte",
        summary="Gestion de l'email, du téléphone et de la double authentification (2FA).",
        steps=[
            "Mon compte → « Sécurité »",
            "Mettre à jour email ou numéro de mobile (pour les codes SMS)",
            "Activer la 2FA : application TOTP (Google Authenticator, etc.) ou codes par email/SMS",
            "Conserver les codes de secours en lieu sûr",
        ],
        url_path="/compte/securite/",
        demo_label="Ouvrir Sécurité",
    ),
    PresentationSlide(
        id="mus-notifications",
        title="Notifications",
        summary="Boîte de réception des alertes : invitations, sondages, feuilles de route, messages staff.",
        steps=[
            "Mon compte → « Notifications » (ou cloche si visible)",
            "Lire une notification : clic pour ouvrir la page concernée",
            "Marquer comme lu ou « traité » selon le type",
            "« Tout marquer comme lu » pour vider la pile",
        ],
        url_path="/compte/notifications/",
        demo_label="Ouvrir les notifications",
    ),
    PresentationSlide(
        id="mus-push",
        title="Notifications push (navigateur)",
        summary="Alertes en temps réel sur ordinateur ou téléphone, même hors du site.",
        steps=[
            "À la première visite, le navigateur peut proposer d'autoriser les notifications",
            "Accepter pour recevoir rappels (sondages, messages, feuilles de route)",
            "Gérable depuis les préférences du navigateur si besoin de désactiver",
        ],
        url_path="/compte/",
        demo_label="Ouvrir Mon compte",
    ),
    PresentationSlide(
        id="planning-calendrier",
        title="Planning — calendrier 12 mois",
        summary="Vue d'ensemble de tous les événements de l'orchestre sur une année glissante.",
        steps=[
            "Coulisses → Planning (page par défaut)",
            "Naviguer mois par mois ; les pastilles indiquent le type d'événement",
            "Cliquer sur une date pour voir le détail",
            "La météo s'affiche pour les dates proches (si lieu renseigné)",
        ],
        url_name="planning:dashboard",
        demo_label="Ouvrir le calendrier",
    ),
    PresentationSlide(
        id="planning-moi",
        title="Planning — Mes dates",
        summary="Vos participations personnelles : concerts, répétitions, statuts, remplacements.",
        steps=[
            "Planning → « Mes dates » (onglet ou lien dédié)",
            "Voir vos engagements à venir et passés",
            "Repérer rapidement ce qui attend une réponse (invitation en attente)",
            "Accéder au matériel qui vous est assigné",
        ],
        url_name="planning:my_board",
        demo_label="Ouvrir Mes dates",
    ),
    PresentationSlide(
        id="planning-event",
        title="Fiche événement",
        summary="Détail d'un concert ou événement : effectif, setlist, matériel, lien chat.",
        steps=[
            "Depuis le calendrier ou Mes dates, ouvrir un événement",
            "Consulter lieu, horaires, participants, programme",
            "Accéder à la feuille de route si vous êtes convoqué",
            "Rejoindre le salon de chat lié à l'événement",
        ],
        url_name="planning:dashboard",
        demo_label="Ouvrir le planning (choisir un événement)",
    ),
    PresentationSlide(
        id="planning-repondre",
        title="Répondre à une invitation",
        summary="Confirmer sa présence, décliner ou répondre « peut-être » à un événement.",
        steps=[
            "Ouvrir la fiche événement ou cliquer le lien depuis une notification",
            "Trouver votre nom dans la liste des participants",
            "Choisir : Oui / Non / Peut-être",
            "La réponse est enregistrée immédiatement ; le staff est informé",
        ],
        url_name="planning:my_board",
        demo_label="Ouvrir Mes dates",
    ),
    PresentationSlide(
        id="planning-sondage",
        title="Sondage de disponibilités",
        summary="Vote pour choisir une date de répétition ou de réunion quand plusieurs créneaux sont proposés.",
        steps=[
            "Recevoir une notification ou voir le sondage dans le planning",
            "Ouvrir le sondage : chaque ligne = un créneau possible",
            "Cocher vos disponibilités (oui / non / si besoin)",
            "Valider avant la date limite indiquée",
        ],
        url_name="planning:dashboard",
        demo_label="Ouvrir le planning",
    ),
    PresentationSlide(
        id="planning-feuille-route",
        title="Feuille de route",
        summary="Document opérationnel d'un événement : horaires, contacts, consignes logistiques.",
        steps=[
            "Depuis la fiche événement → « Feuille de route »",
            "Accessible uniquement si vous participez à l'événement",
            "Lire les horaires de balance, concert, départ",
            "Le staff peut notifier quand la feuille est mise à jour",
        ],
        url_name="planning:my_board",
        demo_label="Ouvrir Mes dates",
    ),
    PresentationSlide(
        id="planning-remplacement",
        title="Remplacements",
        summary="Proposer un remplaçant ou prendre la place d'un musicien indisponible.",
        steps=[
            "Si vous déclinez : option « Proposer un remplaçant » (nom du collègue)",
            "Si un créneau est libre : un musicien peut « Prendre la place » (claim)",
            "Le staff valide les remplacements si nécessaire",
            "Suivre l'état dans la fiche événement",
        ],
        url_name="planning:my_board",
        demo_label="Ouvrir Mes dates",
    ),
    PresentationSlide(
        id="planning-materiel",
        title="Matériel assigné",
        summary="Suivi du matériel confié pour un événement (sono, pupitres, etc.).",
        steps=[
            "Fiche événement ou Mes dates → section Matériel",
            "Voir ce qui vous est assigné",
            "Mettre à jour le statut : pris, rendu, problème signalé",
            "Aide le staff à savoir où en est chaque équipement",
        ],
        url_name="planning:my_board",
        demo_label="Ouvrir Mes dates",
    ),
    PresentationSlide(
        id="planning-proposer",
        title="Proposer un événement",
        summary="Les musiciens (et adhérents actifs) peuvent suggérer un nouveau concert ou événement.",
        steps=[
            "Planning → « Proposer un événement »",
            "Remplir : titre, type, date souhaitée, lieu, description",
            "Envoyer — le staff examine et crée l'événement officiel si validé",
        ],
        url_name="planning:propose_event",
        demo_label="Ouvrir Proposer un événement",
    ),
    PresentationSlide(
        id="planning-profil",
        title="Profil musicien",
        summary="Mettre à jour ses instruments, sections et informations visibles par le staff.",
        steps=[
            "Planning → « Mon profil » (ou section profil)",
            "Modifier instruments, section, coordonnées utiles à l'orchestre",
            "Enregistrer — les infos alimentent les convocations et le répertoire filtré",
        ],
        url_path="/planning/profile/",
        demo_label="Ouvrir le profil musicien",
    ),
    # ── Répertoire ────────────────────────────────────────────────
    PresentationSlide(
        id="sec-repertoire",
        title="Répertoire & partitions",
        summary="Bibliothèque des morceaux, partitions PDF et enregistrements de référence.",
        is_section=True,
        section="Répertoire",
    ),
    PresentationSlide(
        id="repertoire-liste",
        title="Liste des morceaux",
        summary="Tous les morceaux du répertoire, filtrables par instrument.",
        steps=[
            "Coulisses → Répertoire",
            "Parcourir la liste ou chercher un titre",
            "Filtrer par instrument pour voir les morceaux où vous avez une partie",
        ],
        url_name="repertoire:list",
        demo_label="Ouvrir le répertoire",
    ),
    PresentationSlide(
        id="repertoire-morceau",
        title="Fiche morceau",
        summary="Détail d'un morceau : métadonnées, tempo, style, liens vers partitions et audio.",
        steps=[
            "Cliquer sur un morceau dans la liste",
            "Lire les informations (compositeur, arrangement, tempo…)",
            "Voir les partitions disponibles pour votre instrument",
            "Écouter l'audio de référence si présent",
        ],
        url_name="repertoire:list",
        demo_label="Ouvrir le répertoire",
    ),
    PresentationSlide(
        id="repertoire-partition",
        title="Télécharger sa partition",
        summary="PDF de la partie instrumentale, adapté à votre profil musicien.",
        steps=[
            "Sur la fiche morceau, section « Partitions »",
            "Cliquer sur votre instrument / votre partie",
            "Le PDF se télécharge ou s'ouvre dans le navigateur",
            "Conserver le fichier pour répétition hors ligne",
        ],
        url_name="repertoire:list",
        demo_label="Ouvrir le répertoire",
    ),
    PresentationSlide(
        id="repertoire-salon",
        title="Salon de discussion d'un morceau",
        summary="Chat dédié à un morceau pour échanger avec les musiciens concernés.",
        steps=[
            "Fiche morceau → « Ouvrir le salon » (ou équivalent)",
            "Crée ou rejoint le salon lié à ce morceau",
            "Échanger conseils, questions sur la partie",
            "Retrouver le salon dans Chat → salons de morceaux",
        ],
        url_name="repertoire:list",
        demo_label="Ouvrir le répertoire",
    ),
    # ── Chat ──────────────────────────────────────────────────────
    PresentationSlide(
        id="sec-chat",
        title="Chat de l'orchestre",
        summary="Messagerie instantanée entre musiciens : orchestre, événements, morceaux.",
        is_section=True,
        section="Chat",
    ),
    PresentationSlide(
        id="chat-salons",
        title="Liste des salons",
        summary="Tous vos salons de discussion : orchestre, événements, morceaux.",
        steps=[
            "Coulisses → Chat",
            "Salon « Orchestre » : discussion générale (tous les musiciens)",
            "Salons « Événement » : un par concert/répétition",
            "Salons « Morceau » : créés depuis le répertoire",
        ],
        url_name="chat:list",
        demo_label="Ouvrir le chat",
    ),
    PresentationSlide(
        id="chat-messages",
        title="Envoyer un message",
        summary="Discussion en temps réel avec pièces jointes, mentions et réactions.",
        steps=[
            "Ouvrir un salon",
            "Taper un message en bas de page, Entrée ou bouton Envoyer",
            "Joindre un fichier (partition, photo…) via le trombone",
            "Mentionner un collègue avec @ suivi du nom",
            "Réagir avec un emoji sur un message existant",
        ],
        url_name="chat:list",
        demo_label="Ouvrir le chat",
    ),
    PresentationSlide(
        id="chat-prefs",
        title="Préférences de notifications",
        summary="Choisir la fréquence des alertes (temps réel ou récap) et les exceptions.",
        steps=[
            "Compte ou Chat → Préférences de notifications",
            "Choisir la fréquence par défaut (temps réel, quotidien, tous les 2/3 jours, hebdo)",
            "Au besoin, contourner par type d’alerte ou par salon (temps réel ou quotidien)",
        ],
        url_name="chat:prefs",
        demo_label="Ouvrir les préférences",
    ),
    # ── Répétitions ───────────────────────────────────────────────
    PresentationSlide(
        id="sec-repetitions",
        title="Répétitions",
        summary="Fiches de répétition avec plan de séance et morceaux.",
        is_section=True,
        section="Répétitions",
    ),
    PresentationSlide(
        id="repetitions-fiche",
        title="Fiche répétition",
        summary="Détail d'une répétition : lieu, horaire, morceaux travaillés, feuille de route.",
        steps=[
            "Depuis le planning, ouvrir une répétition (type dédié)",
            "Consulter le plan : morceaux dans l'ordre, pauses",
            "Indiquer sa propre présence ou absence",
        ],
        url_name="planning:dashboard",
        demo_label="Ouvrir le planning",
    ),
    PresentationSlide(
        id="repetitions-absence",
        title="Signaler une absence",
        summary="Prévenir qu'on ne pourra pas être présent à une répétition.",
        steps=[
            "Sur la fiche répétition, bouton « Absent » ou équivalent",
            "Confirmer l'absence",
            "Option : proposer un remplaçant (même flux que pour les concerts)",
            "Le chef et le staff voient la mise à jour",
        ],
        url_name="planning:my_board",
        demo_label="Ouvrir Mes dates",
    ),
    # ── Divers musicien ───────────────────────────────────────────
    PresentationSlide(
        id="sec-divers",
        title="Aide & retours",
        summary="Outils pour signaler un problème ou proposer une amélioration.",
        is_section=True,
        section="Aide & retours",
    ),
    PresentationSlide(
        id="feedback",
        title="Envoyer un retour",
        summary="Signaler un bug, un souci d'ergonomie ou proposer une nouvelle fonctionnalité.",
        steps=[
            "Sur n'importe quelle page : bouton « Retour » ou icône en bas de page",
            "Choisir le type : bug, confort, idée",
            "Décrire le problème ou la suggestion",
            "Le staff traite dans Administration → Retours ; vous pouvez échanger des messages sur un retour, ou voter sur les idées ouvertes",
        ],
        url_path="/compte/",
        demo_label="Ouvrir Mon compte",
    ),
    PresentationSlide(
        id="guide-tour",
        title="Guides interactifs",
        summary="Parcours pas à pas intégrés au site pour découvrir une section.",
        steps=[
            "À la première visite d'une section, un guide peut se lancer automatiquement",
            "Mon compte → relancer un guide si besoin",
            "Suivre les bulles : Suivant / Précédent / Terminer",
            "Le staff peut mettre à jour ces guides (Administration → Guides)",
        ],
        url_path="/compte/",
        demo_label="Ouvrir Mon compte",
    ),
    PresentationSlide(
        id="fin",
        title="C'est parti !",
        summary="Chaque musicien peut explorer les Coulisses à son rythme. Le staff reste disponible pour aider.",
        steps=[
            "Connectez-vous avec votre email (code ou mot de passe)",
            "Commencez par Planning → Mes dates pour voir vos prochains engagements",
            "Explorez le répertoire et rejoignez le salon Orchestre",
            "En cas de souci : retour sur la page concernée ou contactez le staff",
        ],
        is_section=True,
        section="Conclusion",
    ),
]
