from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0013_must_change_password"),
    ]

    operations = [
        migrations.AddField(
            model_name="usernotification",
            name="archived_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="Masquée du salon tant que non consultée via la vue Archives.",
                null=True,
                verbose_name="Archivée le",
            ),
        ),
        migrations.AddIndex(
            model_name="usernotification",
            index=models.Index(
                fields=["user", "archived_at", "-created_at"],
                name="users_usern_user_id_arch_idx",
            ),
        ),
    ]
