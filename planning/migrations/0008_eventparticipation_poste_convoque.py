from django.db import migrations, models


def forwards_backfill_poste(apps, schema_editor):
    EventParticipation = apps.get_model("planning", "EventParticipation")
    MusicianProfile = apps.get_model("planning", "MusicianProfile")
    profiles = {
        p.user_id: p
        for p in MusicianProfile.objects.all().only(
            "user_id", "poste_titulaire", "poste_remplacant"
        )
    }
    to_update = []
    for part in EventParticipation.objects.all().iterator():
        profile = profiles.get(part.user_id)
        if profile is None:
            continue
        poste = ""
        role_kind = ""
        if profile.poste_titulaire:
            poste = profile.poste_titulaire
            role_kind = "titulaire"
        elif profile.poste_remplacant:
            poste = profile.poste_remplacant
            role_kind = "remplacant"
        if not poste:
            continue
        part.poste = poste
        part.role_kind = role_kind
        to_update.append(part)
        if len(to_update) >= 200:
            EventParticipation.objects.bulk_update(
                to_update, ["poste", "role_kind"]
            )
            to_update = []
    if to_update:
        EventParticipation.objects.bulk_update(to_update, ["poste", "role_kind"])


def backwards_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("planning", "0007_event_propose_poll_launch"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventparticipation",
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
                help_text="Chaise pour laquelle le musicien est convoqué à cette date.",
                max_length=30,
                verbose_name="Poste convoqué",
            ),
        ),
        migrations.AddField(
            model_name="eventparticipation",
            name="role_kind",
            field=models.CharField(
                blank=True,
                choices=[
                    ("titulaire", "Titulaire"),
                    ("remplacant", "Remplaçant"),
                ],
                help_text="Titulaire ou remplaçant pour ce poste.",
                max_length=20,
                verbose_name="Rôle",
            ),
        ),
        migrations.RunPython(forwards_backfill_poste, backwards_noop),
    ]
