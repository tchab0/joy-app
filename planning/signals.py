from django.db.models.signals import post_save
from django.dispatch import receiver

from events.models import Event


@receiver(post_save, sender=Event)
def invite_titulaires_on_new_event(sender, instance, created, **kwargs):
    """
    Convocation auto des titulaires — désactivée par défaut.

    Le flux nominal : salon staff-only à la création, invitations individuelles
    (ou « convoquer les titulaires » côté admin). Opt-in via
    ``event._invite_titulaires = True`` avant save.
    """
    if not created:
        return
    if getattr(instance, "_skip_titulaire_invite", False):
        return
    # Nouveau défaut : pas de convocation auto (salon staff-only).
    if not getattr(instance, "_invite_titulaires", False):
        return
    from planning.services import invite_titulaires_to_event

    invite_titulaires_to_event(instance)
