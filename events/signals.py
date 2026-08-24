from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from core.page_cms import bump_public_events_cache
from events.models import Event, Venue
from events.share_image import invalidate_og_cache


@receiver(post_save, sender=Event)
def clear_concert_og_on_save(sender, instance, **kwargs):
    invalidate_og_cache(instance.slug)
    # Si le slug a changé, l'ancien fichier reste orphelin — nettoyage best-effort
    # via fingerprint à la prochaine génération du nouveau slug.


@receiver(post_delete, sender=Event)
def clear_concert_og_on_delete(sender, instance, **kwargs):
    invalidate_og_cache(getattr(instance, "slug", None))


@receiver(post_save, sender=Venue)
def invalidate_public_pages_on_venue_gps(sender, instance, **kwargs):
    """Accueil / agenda : carte visible dès qu’un lieu reçoit ou perd des coordonnées."""
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not {"latitude", "longitude"} & set(update_fields):
        return
    bump_public_events_cache()
