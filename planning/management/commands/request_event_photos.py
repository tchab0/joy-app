from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from events.models import Event
from planning.services import send_event_photos_requests

User = get_user_model()


class Command(BaseCommand):
    help = (
        "J+7 après un événement confirmé : notifie tous les membres "
        "pour demander photos/vidéos (lien rapide /medias/proposer/)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Liste les événements concernés sans envoyer ni marquer.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Délai en jours après l’événement (défaut : 7).",
        )
        parser.add_argument(
            "--force-event",
            type=int,
            default=0,
            help="Forcer l’envoi pour un Event pk (ignore J+7 et le flag déjà envoyé).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        days = max(1, int(options["days"] or 7))
        force_pk = int(options["force_event"] or 0)
        today = timezone.localdate()
        target_day = today - timedelta(days=days)

        if force_pk:
            events = list(
                Event.objects.filter(pk=force_pk)
                .exclude(statut=Event.Statut.ANNULE)
                .select_related("type", "venue")
            )
        else:
            # Événements dont la date locale tombe exactement à J-days.
            qs = (
                Event.objects.filter(
                    statut=Event.Statut.CONFIRME,
                    photos_request_sent_at__isnull=True,
                )
                .exclude(type__nom__icontains="répétition")
                .exclude(type__nom__icontains="repetition")
                .select_related("type", "venue")
                .order_by("date_debut")
            )
            events = [
                e
                for e in qs
                if timezone.localtime(e.date_debut).date() == target_day
            ]

        if not events:
            self.stdout.write("Aucun événement à traiter.")
            return

        members = list(
            User.objects.filter(is_active=True)
            .filter(Q(is_musician=True) | Q(is_association_member=True))
            .order_by("pk")
        )

        if dry_run:
            for event in events:
                day = timezone.localtime(event.date_debut).date()
                self.stdout.write(
                    f"[dry-run] #{event.pk} « {event.titre} » ({day}) "
                    f"→ {len(members)} membre(s)"
                )
            return

        total_sent = send_event_photos_requests(events, members)
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(events)} événement(s), {total_sent} notification(s) envoyée(s)."
            )
        )
