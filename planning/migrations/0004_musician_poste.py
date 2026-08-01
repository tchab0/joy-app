from django.db import migrations, models


def _normalize(value: str) -> str:
    return (
        (value or "")
        .strip()
        .lower()
        .replace("ème", "e")
        .replace("eme", "e")
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
    )


# Anciennes valeurs libres de `instrument` → codes Poste.
_INSTRUMENT_TO_POSTE = {
    "trompette 1": "trompette_1",
    "1er trompette": "trompette_1",
    "1e trompette": "trompette_1",
    "lead trompette": "trompette_1",
    "trompette 2": "trompette_2",
    "2e trompette": "trompette_2",
    "trompette 3": "trompette_3",
    "3e trompette": "trompette_3",
    "trompette 4": "trompette_4",
    "4e trompette": "trompette_4",
    "trombone 1": "trombone_1",
    "1er trombone": "trombone_1",
    "1e trombone": "trombone_1",
    "trombone 2": "trombone_2",
    "2e trombone": "trombone_2",
    "trombone 3": "trombone_3",
    "3e trombone": "trombone_3",
    "trombone 4": "trombone_4",
    "4e trombone": "trombone_4",
    "trombone basse": "trombone_4",
    "basse trombone": "trombone_4",
    "alto 1": "alto_1",
    "1er alto": "alto_1",
    "1e alto": "alto_1",
    "sax alto 1": "alto_1",
    "alto 2": "alto_2",
    "2e alto": "alto_2",
    "sax alto 2": "alto_2",
    "tenor 1": "tenor_1",
    "1er tenor": "tenor_1",
    "1e tenor": "tenor_1",
    "sax tenor 1": "tenor_1",
    "tenor 2": "tenor_2",
    "2e tenor": "tenor_2",
    "sax tenor 2": "tenor_2",
    "baryton": "baryton",
    "sax baryton": "baryton",
    "baritone": "baryton",
    "bari": "baryton",
    "piano": "piano",
    "guitare": "guitare",
    "guitar": "guitare",
    "basse": "basse",
    "contrebasse": "basse",
    "batterie": "batterie",
    "drums": "batterie",
    "clarinette": "clarinette",
    "clarinet": "clarinette",
    "chant": "chant",
    "voix": "chant",
    "vocal": "chant",
    "percussion": "percussion",
    "percussions": "percussion",
}

_POSTE_TO_INSTRUMENT = {
    "alto_1": "1er alto",
    "alto_2": "2e alto",
    "tenor_1": "1er ténor",
    "tenor_2": "2e ténor",
    "baryton": "Sax baryton",
    "trompette_1": "1er trompette",
    "trompette_2": "2e trompette",
    "trompette_3": "3e trompette",
    "trompette_4": "4e trompette",
    "trombone_1": "1er trombone",
    "trombone_2": "2e trombone",
    "trombone_3": "3e trombone",
    "trombone_4": "4e trombone (basse)",
    "piano": "Piano",
    "guitare": "Guitare",
    "basse": "Basse",
    "batterie": "Batterie",
    "clarinette": "Clarinette",
    "chant": "Chant",
    "percussion": "Percussions",
}


def forwards_instrument_to_poste(apps, schema_editor):
    MusicianProfile = apps.get_model("planning", "MusicianProfile")
    for profile in MusicianProfile.objects.exclude(instrument="").iterator():
        key = _normalize(profile.instrument)
        poste = _INSTRUMENT_TO_POSTE.get(key, "")
        if poste:
            profile.poste = poste
            profile.save(update_fields=["poste"])


def backwards_poste_to_instrument(apps, schema_editor):
    MusicianProfile = apps.get_model("planning", "MusicianProfile")
    for profile in MusicianProfile.objects.exclude(poste="").iterator():
        profile.instrument = _POSTE_TO_INSTRUMENT.get(profile.poste, profile.poste)
        profile.save(update_fields=["instrument"])


class Migration(migrations.Migration):

    dependencies = [
        ("planning", "0003_musician_roster_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="musicianprofile",
            name="poste",
            field=models.CharField(
                blank=True,
                choices=[
                    ("alto_1", "1er alto"),
                    ("alto_2", "2e alto"),
                    ("tenor_1", "1er ténor"),
                    ("tenor_2", "2e ténor"),
                    ("baryton", "Sax baryton"),
                    ("trompette_1", "1er trompette"),
                    ("trompette_2", "2e trompette"),
                    ("trompette_3", "3e trompette"),
                    ("trompette_4", "4e trompette"),
                    ("trombone_1", "1er trombone"),
                    ("trombone_2", "2e trombone"),
                    ("trombone_3", "3e trombone"),
                    ("trombone_4", "4e trombone (basse)"),
                    ("piano", "Piano"),
                    ("guitare", "Guitare"),
                    ("basse", "Basse"),
                    ("batterie", "Batterie"),
                    ("clarinette", "Clarinette"),
                    ("chant", "Chant"),
                    ("percussion", "Percussions"),
                ],
                help_text="Chaise / instrument joué (ex. 1er trompette, 2e alto).",
                max_length=30,
                verbose_name="Poste",
            ),
        ),
        migrations.RunPython(forwards_instrument_to_poste, backwards_poste_to_instrument),
        migrations.RemoveField(
            model_name="musicianprofile",
            name="instrument",
        ),
    ]
