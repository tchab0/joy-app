from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0012_notify_frequency_prefs"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="must_change_password",
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text=(
                    "Mot de passe provisoire : la navigation est bloquée sur "
                    "« Nouveau mot de passe » jusqu’au changement."
                ),
                verbose_name="Doit changer de mot de passe",
            ),
        ),
    ]
