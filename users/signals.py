from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from .models import User
from .roles import GROUP_MEMBER, GROUP_MUSICIAN, sync_user_groups

_ROLE_FIELDS = frozenset(
    {
        "is_musician",
        "is_association_member",
        "membership_expires_at",
    }
)


@receiver(post_save, sender=User)
def user_sync_groups(sender, instance: User, created, update_fields=None, **kwargs):
    if kwargs.get("raw"):
        return
    if created:
        sync_user_groups(instance)
        return
    if update_fields is None or _ROLE_FIELDS.intersection(update_fields):
        sync_user_groups(instance)


@receiver(post_migrate)
def ensure_role_groups(sender, **kwargs):
    if sender.name != "users":
        return

    musician_group, _ = Group.objects.get_or_create(name=GROUP_MUSICIAN)
    member_group, _ = Group.objects.get_or_create(name=GROUP_MEMBER)

    planning_perm = Permission.objects.filter(
        codename="access_planning", content_type__app_label="users"
    ).first()
    member_perm = Permission.objects.filter(
        codename="access_member_area", content_type__app_label="users"
    ).first()

    if planning_perm:
        musician_group.permissions.add(planning_perm)
    if member_perm:
        member_group.permissions.add(member_perm)
