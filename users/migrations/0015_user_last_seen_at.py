from django.db import migrations, models
from django.db.models import F, Max, Q


def backfill_last_seen(apps, schema_editor):
    User = apps.get_model("users", "User")
    User.objects.filter(last_seen_at__isnull=True, last_login__isnull=False).update(
        last_seen_at=F("last_login")
    )

    try:
        UsageEvent = apps.get_model("stats", "UsageEvent")
    except LookupError:
        return

    rows = (
        UsageEvent.objects.exclude(user_id=None)
        .values("user_id")
        .annotate(m=Max("created_at"))
    )
    for row in rows:
        User.objects.filter(pk=row["user_id"]).filter(
            Q(last_seen_at__isnull=True) | Q(last_seen_at__lt=row["m"])
        ).update(last_seen_at=row["m"])


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0014_usernotification_archived_at"),
        ("stats", "0002_publicpageview"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="last_seen_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text=(
                    "Dernière visite authentifiée (session), distincte de last_login "
                    "qui ne se met à jour qu’au formulaire de connexion."
                ),
                null=True,
                verbose_name="Dernière activité",
            ),
        ),
        migrations.RunPython(backfill_last_seen, migrations.RunPython.noop),
    ]
