from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from events.models import Event

User = get_user_model()


@receiver(post_save, sender=User)
def ensure_musician_profile(sender, instance, **kwargs):
    """
    La liste staff (/planning/admin/musiciens/) lit MusicianProfile, pas
    seulement le flag User.is_musician. Cocher « musicien » dans l’admin
    Django doit donc créer le profil (sinon le compte reste invisible).
    """
    if kwargs.get("raw"):
        return
    if not getattr(instance, "is_musician", False):
        return
    update_fields = kwargs.get("update_fields")
    if (
        update_fields is not None
        and "is_musician" not in update_fields
        and not kwargs.get("created")
    ):
        # Évite un SELECT à chaque save partiel (ex. dernière connexion).
        return
    from django.db import OperationalError, ProgrammingError

    from planning.services import get_or_create_profile

    try:
        get_or_create_profile(instance)
    except (ProgrammingError, OperationalError):
        # Schéma planning pas encore migré — ne pas faire échouer le save User.
        pass


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
