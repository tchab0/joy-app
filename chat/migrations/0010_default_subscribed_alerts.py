# Generated manually — alertes salon ON par défaut pour les memberships actives.

from django.db import migrations


def enable_active_subscriptions(apps, schema_editor):
    ChatMembership = apps.get_model("chat", "ChatMembership")
    ChatMembership.objects.filter(left_at__isnull=True, subscribed=False).update(
        subscribed=True
    )


def noop_reverse(apps, schema_editor):
    # Impossible de restaurer qui s’était désabonné volontairement.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0009_chat_message_edited_at"),
    ]

    operations = [
        migrations.RunPython(enable_active_subscriptions, noop_reverse),
    ]
