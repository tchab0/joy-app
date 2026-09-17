# Generated manually for chat-launched polls (dates/text + audience).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0015_chatmessage_thread_event"),
        ("planning", "0018_eventroadmap_misc_info"),
    ]

    operations = [
        migrations.AddField(
            model_name="dateproposal",
            name="option_kind",
            field=models.CharField(
                choices=[("dates", "Dates"), ("text", "Texte")],
                db_index=True,
                default="dates",
                help_text="Dates/heures ou propositions textuelles.",
                max_length=10,
                verbose_name="Type d’options",
            ),
        ),
        migrations.AddField(
            model_name="dateproposal",
            name="audience",
            field=models.CharField(
                choices=[
                    ("room", "Membres du salon"),
                    ("all", "Tous les musiciens"),
                ],
                db_index=True,
                default="room",
                help_text="Qui peut répondre : membres du salon source, ou tous les musiciens.",
                max_length=10,
                verbose_name="Audience",
            ),
        ),
        migrations.AddField(
            model_name="dateproposal",
            name="source_room",
            field=models.ForeignKey(
                blank=True,
                help_text="Salon depuis lequel le sondage a été lancé (accès / notifications).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="polls_launched",
                to="chat.chatroom",
                verbose_name="Salon source",
            ),
        ),
        migrations.AlterField(
            model_name="dateoption",
            name="starts_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Obligatoire pour un sondage de dates ; vide pour une option texte.",
                null=True,
                verbose_name="Début",
            ),
        ),
        migrations.AlterField(
            model_name="dateoption",
            name="proposal",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="options",
                to="planning.dateproposal",
                verbose_name="Sondage",
            ),
        ),
        migrations.AlterModelOptions(
            name="dateproposal",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Sondage",
                "verbose_name_plural": "Sondages",
            },
        ),
        migrations.AlterModelOptions(
            name="dateoption",
            options={
                "ordering": ["sort_order", "starts_at"],
                "verbose_name": "Option de sondage",
                "verbose_name_plural": "Options de sondage",
            },
        ),
    ]
