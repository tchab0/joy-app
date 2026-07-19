import django.db.models.deletion
from django.db import migrations, models


def forwards_sync_sections(apps, schema_editor):
    MusicianProfile = apps.get_model("planning", "MusicianProfile")
    OrchestraSection = apps.get_model("planning", "OrchestraSection")

    poste_section_code = {
        "alto_1": "sax-alto",
        "alto_2": "sax-alto",
        "tenor_1": "sax-tenor",
        "tenor_2": "sax-tenor",
        "baryton": "sax-baryton",
        "clarinette": "clarinette",
        "trompette_1": "trompette",
        "trompette_2": "trompette",
        "trompette_3": "trompette",
        "trompette_4": "trompette",
        "trombone_1": "trombone",
        "trombone_2": "trombone",
        "trombone_3": "trombone",
        "trombone_4": "trombone",
        "piano": "rythmique",
        "guitare": "rythmique",
        "basse": "rythmique",
        "batterie": "rythmique",
        "percussion": "rythmique",
        "chant": "chant",
    }
    section_defaults = {
        "sax-alto": ("Saxophones altos", 10),
        "sax-tenor": ("Saxophones ténors", 20),
        "sax-baryton": ("Saxophone baryton", 30),
        "clarinette": ("Clarinette", 35),
        "trompette": ("Trompettes", 40),
        "trombone": ("Trombones", 50),
        "rythmique": ("Rythmique", 60),
        "chant": ("Chant", 70),
    }

    cache = {}
    for profile in MusicianProfile.objects.all().iterator():
        code = poste_section_code.get(profile.poste_titulaire or "")
        if not code:
            if profile.section_id is not None:
                profile.section_id = None
                profile.save(update_fields=["section_id"])
            continue
        if code not in cache:
            name, order = section_defaults[code]
            section, _ = OrchestraSection.objects.get_or_create(
                code=code,
                defaults={"name": name, "sort_order": order, "is_active": True},
            )
            cache[code] = section
        section = cache[code]
        if profile.section_id != section.pk:
            profile.section_id = section.pk
            profile.save(update_fields=["section_id"])


def backwards_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("planning", "0005_musician_dual_postes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="musicianprofile",
            name="section",
            field=models.ForeignKey(
                blank=True,
                help_text="Déduit automatiquement du poste titulaire.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="musicians",
                to="planning.orchestrasection",
                verbose_name="Pupitre",
            ),
        ),
        migrations.AlterField(
            model_name="musicianprofile",
            name="poste_titulaire",
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
                help_text=(
                    "Chaise pour laquelle le musicien est titulaire "
                    "(convoqué à chaque nouvelle date). Détermine le pupitre."
                ),
                max_length=30,
                verbose_name="Poste titulaire",
            ),
        ),
        migrations.RunPython(forwards_sync_sections, backwards_noop),
    ]
