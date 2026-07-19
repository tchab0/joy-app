from django.db import migrations, models


def forwards_roster_status(apps, schema_editor):
    MusicianProfile = apps.get_model("planning", "MusicianProfile")
    MusicianProfile.objects.filter(is_substitute_pool=True).update(
        roster_status="remplacant"
    )
    MusicianProfile.objects.filter(is_substitute_pool=False).update(
        roster_status="titulaire"
    )


def backwards_roster_status(apps, schema_editor):
    MusicianProfile = apps.get_model("planning", "MusicianProfile")
    MusicianProfile.objects.filter(roster_status="remplacant").update(
        is_substitute_pool=True
    )
    MusicianProfile.objects.exclude(roster_status="remplacant").update(
        is_substitute_pool=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ("planning", "0002_planning_full_features"),
    ]

    operations = [
        migrations.AddField(
            model_name="musicianprofile",
            name="roster_status",
            field=models.CharField(
                choices=[
                    ("titulaire", "Titulaire"),
                    ("remplacant", "Remplaçant"),
                ],
                default="titulaire",
                help_text=(
                    "Les titulaires sont convoqués à chaque nouvelle date ; "
                    "les remplaçants sont sollicités uniquement en cas de besoin."
                ),
                max_length=20,
                verbose_name="Statut",
            ),
        ),
        migrations.RunPython(forwards_roster_status, backwards_roster_status),
        migrations.RemoveField(
            model_name="musicianprofile",
            name="is_substitute_pool",
        ),
    ]
