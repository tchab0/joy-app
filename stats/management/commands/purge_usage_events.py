from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import OperationalError, ProgrammingError
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Purge UsageEvent et PublicPageView plus anciens que "
        "USAGE_EVENT_RETENTION_DAYS."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Rétention en jours (défaut: settings.USAGE_EVENT_RETENTION_DAYS).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche le nombre sans supprimer.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days is None:
            days = int(getattr(settings, "USAGE_EVENT_RETENTION_DAYS", 90))
        cutoff = timezone.now() - timedelta(days=days)
        try:
            from stats.models import PublicPageView, UsageEvent

            usage_qs = UsageEvent.objects.filter(created_at__lt=cutoff)
            public_qs = PublicPageView.objects.filter(created_at__lt=cutoff)
            usage_n = usage_qs.count()
            public_n = public_qs.count()
            if options["dry_run"]:
                self.stdout.write(
                    f"{usage_n} UsageEvent + {public_n} PublicPageView "
                    f"à purger (avant {cutoff:%Y-%m-%d})."
                )
                return
            deleted_u, _ = usage_qs.delete()
            deleted_p, _ = public_qs.delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f"{deleted_u} UsageEvent + {deleted_p} PublicPageView purgé(s)."
                )
            )
        except (ProgrammingError, OperationalError) as exc:
            self.stderr.write(f"Table absente ou erreur DB : {exc}")
