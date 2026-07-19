import logging

from django.db import OperationalError, ProgrammingError
from django.db.models.signals import post_save
from django.dispatch import receiver

from events.models import Event
from planning.models import EventParticipation
from users.models import User

logger = logging.getLogger(__name__)


def _safe_chat_sync(label: str, fn, *args, **kwargs) -> None:
    """Évite un 500 site-wide si les tables chat ne sont pas encore migrées."""
    try:
        fn(*args, **kwargs)
    except (ProgrammingError, OperationalError) as exc:
        logger.warning("Sync chat ignorée (%s): %s", label, exc)


@receiver(post_save, sender=Event)
def ensure_chat_room_on_event(sender, instance, created, **kwargs):
    from chat.services import ensure_event_room

    _safe_chat_sync("event_room", ensure_event_room, instance)


@receiver(post_save, sender=EventParticipation)
def sync_chat_on_participation(sender, instance, created, **kwargs):
    from chat.services import sync_participation_to_chat

    if created:
        _safe_chat_sync("participation", sync_participation_to_chat, instance)


@receiver(post_save, sender=User)
def sync_orchestra_on_musician(sender, instance, **kwargs):
    from chat.services import sync_musician_to_orchestra

    if instance.is_musician and instance.is_active:
        _safe_chat_sync("orchestra", sync_musician_to_orchestra, instance)
