from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0015_user_last_seen_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="calendar_feed_token",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text=(
                    "Secret pour les flux ICS (orchestre / mes dates). "
                    "Régénérable depuis Mon compte."
                ),
                max_length=64,
                null=True,
                unique=True,
                verbose_name="Jeton abonnement agenda",
            ),
        ),
    ]
