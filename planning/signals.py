from django.db.models.signals import post_save
from django.dispatch import receiver

from events.models import Event


@receiver(post_save, sender=Event)
def invite_titulaires_on_new_event(sender, instance, created, **kwargs):
    """Chaque nouvelle date convoque automatiquement tous les titulaires."""
    if not created:
        return
    # Import local pour éviter les imports circulaires au chargement de l’app.
    from planning.services import invite_titulaires_to_event

    invite_titulaires_to_event(instance)
