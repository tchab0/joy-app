from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_contact_jauge_choices"),
    ]

    operations = [
        migrations.AddField(
            model_name="mediaitem",
            name="edite_le",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="mediaitem",
            name="fichier_edite",
            field=models.ImageField(
                blank=True,
                help_text="Version retouchée (HD). L'original reste dans fichier jusqu'à purge J+30.",
                null=True,
                upload_to="medias/edites/%Y/%m/",
            ),
        ),
    ]
