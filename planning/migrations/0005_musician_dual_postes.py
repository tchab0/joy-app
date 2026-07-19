from django.db import migrations, models


def forwards_split_poste(apps, schema_editor):
    MusicianProfile = apps.get_model("planning", "MusicianProfile")
    for profile in MusicianProfile.objects.all().iterator():
        poste = getattr(profile, "poste", "") or ""
        status = getattr(profile, "roster_status", "titulaire") or "titulaire"
        if status == "remplacant":
            profile.poste_remplacant = poste
            profile.poste_titulaire = ""
        else:
            profile.poste_titulaire = poste
            profile.poste_remplacant = ""
        profile.save(update_fields=["poste_titulaire", "poste_remplacant"])


def backwards_merge_poste(apps, schema_editor):
    MusicianProfile = apps.get_model("planning", "MusicianProfile")
    for profile in MusicianProfile.objects.all().iterator():
        if profile.poste_titulaire:
            profile.poste = profile.poste_titulaire
            profile.roster_status = "titulaire"
        elif profile.poste_remplacant:
            profile.poste = profile.poste_remplacant
            profile.roster_status = "remplacant"
        else:
            profile.poste = ""
            profile.roster_status = "titulaire"
        profile.save(update_fields=["poste", "roster_status"])


class Migration(migrations.Migration):

    dependencies = [
        ("planning", "0004_musician_poste"),
    ]

    operations = [
        migrations.AddField(
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
                    "(convoqué à chaque nouvelle date). Laisser vide si non titulaire."
                ),
                max_length=30,
                verbose_name="Poste titulaire",
            ),
        ),
        migrations.AddField(
            model_name="musicianprofile",
            name="poste_remplacant",
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
                    "Chaise pour laquelle le musicien peut être sollicité "
                    "en remplacement. Laisser vide si non remplaçant."
                ),
                max_length=30,
                verbose_name="Poste remplaçant",
            ),
        ),
        migrations.RunPython(forwards_split_poste, backwards_merge_poste),
        migrations.RemoveField(
            model_name="musicianprofile",
            name="poste",
        ),
        migrations.RemoveField(
            model_name="musicianprofile",
            name="roster_status",
        ),
    ]
