from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Event
from planning.models import EventParticipation, ParticipationStatus
from users.models import User


class Command(BaseCommand):
    help = "Crée des statuts de participation et des participations de démonstration"

    def handle(self, *args, **options):
        statuses = [
            {"code": "invited", "label": "Invité", "color_token": "warning", "sort_order": 10},
            {"code": "confirmed", "label": "Confirmé", "color_token": "success", "sort_order": 20},
            {"code": "declined", "label": "Refusé", "color_token": "danger", "sort_order": 30},
            {"code": "replacement_needed", "label": "Remplacement demandé", "color_token": "neutral", "sort_order": 40},
        ]

        created_statuses = {}
        for payload in statuses:
            status, _ = ParticipationStatus.objects.update_or_create(
                code=payload["code"],
                defaults={
                    "label": payload["label"],
                    "color_token": payload["color_token"],
                    "sort_order": payload["sort_order"],
                    "is_active": True,
                },
            )
            created_statuses[status.code] = status

        users = list(
            User.objects.filter(is_active=True).order_by("last_name", "first_name", "id")[:8]
        )

        if not users:
            self.stdout.write(self.style.WARNING("Aucun utilisateur actif trouvé."))
            return

        now = timezone.now()
        events = list(
            Event.objects.filter(date_debut__gte=now)
            .order_by("date_debut", "id")[:6]
        )

        if not events:
            self.stdout.write(self.style.WARNING("Aucun concert futur trouvé."))
            return

        matrix = [
            "confirmed",
            "invited",
            "declined",
            "replacement_needed",
        ]

        created_count = 0
        updated_count = 0

        for event_index, event in enumerate(events):
            for user_index, user in enumerate(users):
                status_code = matrix[(event_index + user_index) % len(matrix)]
                _, created = EventParticipation.objects.update_or_create(
                    event=event,
                    user=user,
                    defaults={
                        "status": created_statuses[status_code],
                        "comment": "",
                    },
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed planning terminé : {len(created_statuses)} statuts, "
                f"{created_count} participations créées, {updated_count} mises à jour."
            )
        )
