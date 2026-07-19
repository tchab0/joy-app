from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0004_event_contact_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="event",
            name="public",
            field=models.BooleanField(
                default=False,
                help_text="Coché = l’événement apparaît sur l’accueil et /concerts/.",
                verbose_name="Visible sur le site public",
            ),
        ),
        migrations.AddField(
            model_name="event",
            name="organisme",
            field=models.CharField(
                blank=True,
                help_text="Association, mairie, festival… qui organise l’événement.",
                max_length=200,
                verbose_name="Organisme organisateur",
            ),
        ),
        migrations.AddField(
            model_name="event",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                help_text="Festival, saison ou manifestation dans laquelle s’inscrit cet événement.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sous_evenements",
                to="events.event",
                verbose_name="Événement parent",
            ),
        ),
    ]
