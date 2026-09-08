from __future__ import annotations

from django.core.management.base import BaseCommand

from users.digest import send_due_notification_digests


class Command(BaseCommand):
    help = (
        "Envoie les récaps d’alertes dus (chat + autres notifications) "
        "selon les fréquences choisies par chaque utilisateur."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Calcule les digests sans les envoyer.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        sent = send_due_notification_digests(dry_run=dry_run)
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"Dry-run : {sent} digest(s) auraient été envoyés.")
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"Digests envoyés : {sent}"))
