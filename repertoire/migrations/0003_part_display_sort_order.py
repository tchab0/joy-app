# Generated manually — backfill Part.sort_order for display order.

from django.db import migrations

# Aligné sur repertoire.models.PART_DISPLAY_ORDER / PartPoste.
_PART_DISPLAY_ORDER = (
    "conducteur",
    "chant",
    "alto_1",
    "alto_2",
    "tenor_1",
    "tenor_2",
    "baryton",
    "clarinette",
    "trompette_1",
    "trompette_2",
    "trompette_3",
    "trompette_4",
    "trombone_1",
    "trombone_2",
    "trombone_3",
    "trombone_4",
    "piano",
    "guitare",
    "basse",
    "batterie",
    "percussion",
    "autre",
)


def forwards(apps, schema_editor):
    Part = apps.get_model("repertoire", "Part")
    sort_map = {code: index for index, code in enumerate(_PART_DISPLAY_ORDER)}
    for part in Part.objects.all().iterator():
        desired = sort_map.get(part.poste, 999)
        if part.sort_order != desired:
            Part.objects.filter(pk=part.pk).update(sort_order=desired)


def backwards(apps, schema_editor):
    Part = apps.get_model("repertoire", "Part")
    Part.objects.all().update(sort_order=0)


class Migration(migrations.Migration):

    dependencies = [
        ("repertoire", "0002_piece_youtube_and_audio"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
