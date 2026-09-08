# Generated manually — salons chat par pupitre (sax, trompettes, trombones, rythmique).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0010_default_subscribed_alerts"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatroom",
            name="section_key",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Identifiant stable du salon pupitre (ex. sax, trompettes).",
                max_length=40,
                verbose_name="Clé pupitre",
            ),
        ),
        migrations.AlterField(
            model_name="chatroom",
            name="kind",
            field=models.CharField(
                choices=[
                    ("orchestra", "Orchestre"),
                    ("event", "Événement"),
                    ("piece", "Morceau"),
                    ("staff", "Staff"),
                    ("section", "Pupitre"),
                ],
                db_index=True,
                max_length=20,
                verbose_name="Type",
            ),
        ),
        migrations.AddConstraint(
            model_name="chatroom",
            constraint=models.UniqueConstraint(
                condition=models.Q(("kind", "section"))
                & ~models.Q(("section_key", "")),
                fields=("section_key",),
                name="unique_section_chat_room_key",
            ),
        ),
    ]
