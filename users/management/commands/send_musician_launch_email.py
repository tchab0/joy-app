"""Envoie l’e-mail de lancement Coulisses à tous les musiciens actifs.

Par défaut : dry-run (compte les destinataires, n’envoie rien).
Envoi réel uniquement avec ``--send`` (après validation du texte).

    DJANGO_SETTINGS_MODULE=config.settings.prod \\
      python manage.py send_musician_launch_email

    DJANGO_SETTINGS_MODULE=config.settings.prod \\
      python manage.py send_musician_launch_email --apply-passwords --send --to thierry.chabot@ik.me

    DJANGO_SETTINGS_MODULE=config.settings.prod \\
      python manage.py send_musician_launch_email --send
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

from users.management.commands.import_adherents_csv import DEFAULT_PASSWORD

User = get_user_model()

SUBJECT = "Jazz Orchestra Yonnais — vos accès Coulisses & nouveautés (mail automatique)"

LOGIN_URL = "https://jazz-orchestra-yonnais.fr/compte/connexion/"

# Conservent leur mot de passe actuel (pas de reset Joy-joy-joy).
KEEP_PASSWORD_USERNAMES = frozenset({"chloé", "thierry", "thierry.bussy"})

# Comptes de test / placeholders exclus de l’envoi massif.
SKIP_EMAIL_SUFFIXES = (".fake.net", "@fake.net")


def _keeps_password(user) -> bool:
    return (user.username or "") in KEEP_PASSWORD_USERNAMES


def build_body(user) -> str:
    first = (user.first_name or "").strip() or user.username
    email = (user.email or "").strip()
    username = user.username

    if _keeps_password(user):
        password_block = "Mot de passe : celui déjà choisi"
    else:
        password_block = (
            f"Mot de passe provisoire : {DEFAULT_PASSWORD}\n"
            "  (à changer à la première connexion)"
        )

    return f"""Bonjour {first},

Ceci est un message automatique envoyé depuis le site du Jazz Orchestra Yonnais.

L’espace musiciens « Coulisses » est prêt à être testé. Voici vos informations de connexion personnelles.

Vos accès
Site : {LOGIN_URL}
Identifiant : {username}
E-mail : {email}
{password_block}

À tester en priorité
• Planning (calendrier, Mes dates, Oui / Peut-être / Non)
• Proposer une idée / date au big band
• Sondages de dates
• Répertoire (partitions filtrées)
• Chat → Salons (orchestre + salons par pupitre)

Répétition de lundi prochain
Aussitôt après l’envoi de ce mail, la répétition du lundi 14 septembre 2026 sera créée.
Exercice : trouver comment indiquer votre absence/présence (modifiable jusqu’au dernier moment.)

Vos retours sont essentiels !
Bugs, oublis (ex. salons par pupitre), idées d’amélioration
→ pied de page « Signaler un bug… » / Mon compte / chat

— L’équipe JOY (message automatique)
"""


def _mask_email(email: str) -> str:
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    keep = local[:1] if local else "*"
    return f"{keep}***@{domain}"


def _is_skipped_email(email: str) -> bool:
    e = (email or "").strip().lower()
    return any(e.endswith(suf) for suf in SKIP_EMAIL_SUFFIXES)


class _PreviewUser:
    """Destinataire factice pour l’aperçu dry-run (pas de données perso)."""

    first_name = "Camille"
    username = "camille.exemple"
    email = "camille.exemple@example.com"


class Command(BaseCommand):
    help = (
        "E-mail de lancement Coulisses aux musiciens actifs (e-mail en base). "
        "Dry-run par défaut ; --send pour envoyer réellement."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--send",
            action="store_true",
            help="Envoie réellement les e-mails (sinon dry-run).",
        )
        parser.add_argument(
            "--to",
            type=str,
            default="",
            help="Limiter à une adresse e-mail (test avant envoi global).",
        )
        parser.add_argument(
            "--include-fake",
            action="store_true",
            help="Inclure aussi les adresses *@fake.net (exclues par défaut).",
        )
        parser.add_argument(
            "--apply-passwords",
            action="store_true",
            help=(
                "Réinitialise Joy-joy-joy + must_change_password pour tous "
                "sauf chloé / thierry / thierry.bussy."
            ),
        )

    def handle(self, *args, **options):
        do_send = bool(options["send"])
        only_to = (options.get("to") or "").strip().lower()
        include_fake = bool(options["include_fake"])
        apply_passwords = bool(options["apply_passwords"])

        qs = (
            User.objects.filter(is_musician=True, is_active=True)
            .exclude(email="")
            .order_by("last_name", "first_name", "username")
        )
        if only_to:
            qs = qs.filter(email__iexact=only_to)
            if not qs.exists():
                raise CommandError(f"Aucun musicien actif avec l’e-mail « {only_to} ».")

        recipients = []
        skipped = []
        for u in qs:
            email = (u.email or "").strip()
            if not include_fake and _is_skipped_email(email):
                skipped.append(u)
                continue
            recipients.append(u)

        keep_n = sum(1 for u in recipients if _keeps_password(u))
        reset_n = len(recipients) - keep_n

        self.stdout.write(
            f"Destinataires : {len(recipients)} "
            f"(conservent MDP : {keep_n} ; Joy-joy-joy : {reset_n})"
        )
        if skipped:
            self.stdout.write(
                f"Exclus (@fake.net) : {len(skipped)} "
                f"({', '.join(u.username for u in skipped)})"
            )
        self.stdout.write(f"Sujet : {SUBJECT}")
        self.stdout.write(f"From : {settings.DEFAULT_FROM_EMAIL}")
        for u in recipients:
            kind = "gardé" if _keeps_password(u) else "Joy-joy-joy"
            self.stdout.write(
                f"  - {u.username} <{_mask_email(u.email)}> [{kind}]"
            )

        if apply_passwords:
            # Appliqué sur TOUS les musiciens concernés (pas seulement --to),
            # sauf si --to est utilisé : alors seulement ce destinataire.
            apply_qs = recipients
            if not only_to:
                apply_qs = []
                for u in User.objects.filter(is_musician=True, is_active=True):
                    if _is_skipped_email(u.email or "") and not include_fake:
                        continue
                    apply_qs.append(u)
            n_reset = 0
            n_kept = 0
            for u in apply_qs:
                if _keeps_password(u):
                    n_kept += 1
                    continue
                u.set_password(DEFAULT_PASSWORD)
                u.must_change_password = True
                u.save(update_fields=["password", "must_change_password"])
                n_reset += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"Mots de passe : {n_reset} → Joy-joy-joy ; {n_kept} conservés."
                )
            )

        if not do_send:
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run : aucun e-mail envoyé. Relancer avec --send après validation."
                )
            )
            self.stdout.write(
                "Aperçu anonymisé du corps (placeholders, variante provisoire) :\n"
                + build_body(_PreviewUser())
            )
            return

        if not getattr(settings, "EMAIL_SENDING_ENABLED", True):
            raise CommandError(
                "EMAIL_SENDING_ENABLED=false — envoi e-mail en pause."
            )

        sent = 0
        errors = 0
        for user in recipients:
            email = (user.email or "").strip()
            try:
                send_mail(
                    subject=SUBJECT,
                    message=build_body(user),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=False,
                )
                sent += 1
            except Exception as exc:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(f"Échec pour user_id={user.pk} : {exc}")
                )

        self.stdout.write(
            self.style.SUCCESS(f"Envoyés : {sent} — échecs : {errors}")
        )
        if errors:
            raise CommandError(f"{errors} envoi(s) en échec.")
