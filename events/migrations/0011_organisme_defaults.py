from django.db import migrations

# Types d’organisateurs proposés par défaut (liste typeahead).
DEFAULT_ORGANISMES = (
    "Mairie",
    "Particulier",
    "Entreprise",
    "Association",
    "Festival",
    "Comité des fêtes",
    "École / Conservatoire",
    "Collectivité",
    "Office de tourisme",
    "Autre",
)


def seed_default_organismes(apps, schema_editor):
    Organisme = apps.get_model("events", "Organisme")
    for nom in DEFAULT_ORGANISMES:
        Organisme.objects.get_or_create(nom=nom)


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0010_organisme"),
    ]

    operations = [
        migrations.RunPython(seed_default_organismes, migrations.RunPython.noop),
    ]
