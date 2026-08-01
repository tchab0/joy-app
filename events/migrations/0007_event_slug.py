# Generated manually — Event.slug for public concert URLs

from django.db import migrations, models
from django.utils.text import slugify


def populate_slugs(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    used = set(
        s for s in Event.objects.exclude(slug="").values_list("slug", flat=True) if s
    )
    for event in Event.objects.all().order_by("pk"):
        if event.slug:
            used.add(event.slug)
            continue
        base = slugify(event.titre) or "concert"
        if event.date_debut:
            base = f"{base}-{event.date_debut.strftime('%Y-%m-%d')}"
        base = base[:300]
        candidate = base
        n = 2
        while candidate in used:
            candidate = f"{base}-{n}"
            n += 1
        event.slug = candidate
        event.save(update_fields=["slug"])
        used.add(candidate)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0006_event_proposed_by"),
    ]

    operations = [
        # CharField sans index pour éviter le double _like (AddField Slug + Alter unique).
        migrations.AddField(
            model_name="event",
            name="slug",
            field=models.CharField(blank=True, default="", max_length=320),
            preserve_default=False,
        ),
        migrations.RunPython(populate_slugs, noop_reverse),
        migrations.AlterField(
            model_name="event",
            name="slug",
            field=models.SlugField(
                blank=True,
                help_text="URL publique /concerts/<slug>/ — généré automatiquement si vide.",
                max_length=320,
                unique=True,
            ),
        ),
    ]
