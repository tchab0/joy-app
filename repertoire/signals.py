import logging

from django.db import OperationalError, ProgrammingError
from django.db.models.signals import post_save
from django.dispatch import receiver

from users.models import User

logger = logging.getLogger(__name__)


def _safe(label: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except (ProgrammingError, OperationalError) as exc:
        logger.warning("Sync répertoire/chat ignorée (%s): %s", label, exc)


@receiver(post_save, sender=User)
def sync_musician_to_piece_rooms(sender, instance, **kwargs):
    """Nouveau musicien → tous les salons morceau actifs (comme Orchestre)."""
    if not (instance.is_musician and instance.is_active):
        return

    def _sync():
        from chat.services import sync_musician_to_piece_rooms as sync_fn

        sync_fn(instance)

    _safe("piece_rooms", _sync)
