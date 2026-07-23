from django.db import migrations, models


def seed_organismes_from_events(apps, schema_editor):
    Organisme = apps.get_model("events", "Organisme")
    Event = apps.get_model("events", "Event")
    names = (
        Event.objects.exclude(organisme="")
        .exclude(organisme__isnull=True)
        .values_list("organisme", flat=True)
        .distinct()
    )
    for raw in names:
        nom = (raw or "").strip()[:200]
        if nom:
            Organisme.objects.get_or_create(nom=nom)


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0009_event_photos_request_sent_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="Organisme",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("nom", models.CharField(max_length=200, unique=True)),
            ],
            options={
                "verbose_name": "Organisme",
                "ordering": ["nom"],
            },
        ),
        migrations.RunPython(seed_organismes_from_events, migrations.RunPython.noop),
    ]
