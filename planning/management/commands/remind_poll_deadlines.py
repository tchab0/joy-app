from __future__ import annotations

from django.core.management.base import BaseCommand

from planning.services import send_due_poll_deadline_reminders


class Command(BaseCommand):
    help = (
        "Relance les musiciens n’ayant pas répondu aux sondages OPEN "
        "dont la date limite tombe dans une semaine."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Liste les sondages concernés sans envoyer ni marquer.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Jours avant la deadline (défaut : 7).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        days = max(1, int(options["days"] or 7))
        treated, sent = send_due_poll_deadline_reminders(
            dry_run=dry_run,
            days_before=days,
        )
        if not treated:
            self.stdout.write("Aucun rappel deadline sondage dû.")
            return
        if dry_run:
            self.stdout.write(
                f"[dry-run] {treated} sondage(s) à relancer (J−{days})."
            )
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"{treated} sondage(s), {sent} notification(s) envoyée(s)."
            )
        )
