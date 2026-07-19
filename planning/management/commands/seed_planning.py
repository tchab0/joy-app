from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Event, EventType
from planning.models import (
    EquipmentItem,
    EventParticipation,
    MusicianProfile,
    OrchestraSection,
)
from planning.services import ensure_participation_statuses
from users.models import User


DEFAULT_SECTIONS = [
    ("sax-alto", "Saxophones altos", 10),
    ("sax-tenor", "Saxophones ténors", 20),
    ("sax-baryton", "Saxophone baryton", 30),
    ("clarinette", "Clarinette", 35),
    ("trompette", "Trompettes", 40),
    ("trombone", "Trombones", 50),
    ("rythmique", "Rythmique", 60),
    ("chant", "Chant", 70),
]

DEFAULT_EQUIPMENT = [
    ("Pupitre chef", "Scène"),
    ("Sonorisation portable", "Sono"),
    ("Câbles XLR", "Sono"),
    ("Partition complète", "Partitions"),
    ("Véhicule transport", "Transport"),
]


class Command(BaseCommand):
    help = "Crée statuts, pupitres, matériel et participations de démonstration"

    def handle(self, *args, **options):
        statuses = ensure_participation_statuses()
        self.stdout.write(f"{len(statuses)} statuts OK")

        for code, name, order in DEFAULT_SECTIONS:
            OrchestraSection.objects.update_or_create(
                code=code,
                defaults={"name": name, "sort_order": order, "is_active": True},
            )
        self.stdout.write(f"{len(DEFAULT_SECTIONS)} pupitres OK")

        for name, category in DEFAULT_EQUIPMENT:
            EquipmentItem.objects.update_or_create(
                name=name,
                defaults={"category": category, "is_active": True},
            )
        self.stdout.write(f"{len(DEFAULT_EQUIPMENT)} matériels OK")

        EventType.objects.get_or_create(nom="Répétition")
        EventType.objects.get_or_create(nom="Concert")

        sections = list(OrchestraSection.objects.filter(is_active=True))
        users = list(
            User.objects.filter(is_active=True, is_musician=True).order_by(
                "last_name", "first_name", "id"
            )[:12]
        )
        if not users:
            users = list(
                User.objects.filter(is_active=True).order_by("id")[:8]
            )

        for i, user in enumerate(users):
            profile, _ = MusicianProfile.objects.get_or_create(user=user)
            if sections and not profile.section_id:
                profile.section = sections[i % len(sections)]
                profile.save(update_fields=["section"])

        if not users:
            self.stdout.write(self.style.WARNING("Aucun utilisateur trouvé."))
            return

        now = timezone.now()
        events = list(
            Event.objects.filter(date_debut__gte=now).order_by("date_debut", "id")[:6]
        )
        if not events:
            self.stdout.write(self.style.WARNING("Aucun concert futur trouvé."))
            return

        matrix = ["confirmed", "invited", "maybe", "declined", "replacement_needed"]
        created_count = 0
        updated_count = 0
        for event_index, event in enumerate(events):
            for user_index, user in enumerate(users):
                status_code = matrix[(event_index + user_index) % len(matrix)]
                _, created = EventParticipation.objects.update_or_create(
                    event=event,
                    user=user,
                    defaults={"status": statuses[status_code], "comment": ""},
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed planning terminé : {created_count} participations créées, "
                f"{updated_count} mises à jour."
            )
        )
