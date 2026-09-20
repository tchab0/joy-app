# Generated manually for morning-of-event reminders.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0015_chatmessage_thread_event"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="morning_reminder_sent_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Horodatage du rappel joyeux du matin (présents + feuille de route + météo).",
                null=True,
                verbose_name="Rappel matinal envoyé",
            ),
        ),
    ]
