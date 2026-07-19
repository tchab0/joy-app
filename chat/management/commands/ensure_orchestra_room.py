from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from chat.services import (
    ensure_event_room,
    ensure_orchestra_room,
    sync_musician_to_orchestra,
    sync_participation_to_chat,
)
from events.models import Event
from planning.models import EventParticipation

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Crée le salon Orchestre, synchronise les musiciens, "
        "et aligne salons/memberships sur les événements existants."
    )

    def handle(self, *args, **options):
        room = ensure_orchestra_room()
        n_musicians = 0
        for user in User.objects.filter(is_musician=True, is_active=True):
            sync_musician_to_orchestra(user)
            n_musicians += 1

        n_events = 0
        for event in Event.objects.all():
            ensure_event_room(event)
            n_events += 1

        n_parts = 0
        for part in EventParticipation.objects.select_related("event", "user"):
            sync_participation_to_chat(part)
            n_parts += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Salon « {room.title} » — {n_musicians} musicien(s), "
                f"{n_events} salon(s) événement, {n_parts} participation(s) sync."
            )
        )
