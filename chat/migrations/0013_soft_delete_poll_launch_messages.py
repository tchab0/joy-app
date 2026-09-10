# Soft-delete automatic availability-poll launch messages in chat rooms.

from django.db import migrations
from django.utils import timezone


def soft_delete_poll_launch_messages(apps, schema_editor):
    ChatMessage = apps.get_model("chat", "ChatMessage")
    ChatMessage.objects.filter(
        kind="poll_launch",
        deleted_at__isnull=True,
    ).update(deleted_at=timezone.now())


def noop_reverse(apps, schema_editor):
    # Soft-deleted timestamps are not restored (would resurrect stale notices).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0012_notify_frequency_prefs"),
    ]

    operations = [
        migrations.RunPython(soft_delete_poll_launch_messages, noop_reverse),
    ]
