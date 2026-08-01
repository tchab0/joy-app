# Generated manually for EventType.is_rehearsal

from django.db import migrations, models


def seed_rehearsal_flag(apps, schema_editor):
    EventType = apps.get_model("events", "EventType")
    for et in EventType.objects.all():
        nom = (et.nom or "").strip().lower()
        want = "répétition" in nom or "repetition" in nom
        if et.is_rehearsal != want:
            et.is_rehearsal = want
            et.save(update_fields=["is_rehearsal"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0011_organisme_defaults"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventtype",
            name="is_rehearsal",
            field=models.BooleanField(
                default=False,
                help_text="Coché = ce type est une répétition (calendrier, absences, contact masqué).",
                verbose_name="Répétition",
            ),
        ),
        migrations.RunPython(seed_rehearsal_flag, noop_reverse),
    ]
