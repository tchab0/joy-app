from __future__ import annotations

from django.core.management.base import BaseCommand

from planning.services import send_due_maybe_reminds


class Command(BaseCommand):
    help = (
        "Relance les musiciens encore en « peut-être » dont la date "
        "de rappel est due (hebdo ou date choisie)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Liste les participations concernées sans envoyer ni avancer la date.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        treated, sent = send_due_maybe_reminds(dry_run=dry_run)
        if not treated:
            self.stdout.write("Aucune relance « peut-être » due.")
            return
        if dry_run:
            self.stdout.write(
                f"[dry-run] {treated} participation(s) à relancer."
            )
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"{treated} participation(s), {sent} notification(s) envoyée(s)."
            )
        )
