"""Consolide OrchestraSection en pupitres = familles d’instruments."""

import django.db.models.deletion
from django.db import migrations, models

# Anciens codes granulaires → famille (aligné salons chat).
OLD_TO_NEW = {
    "sax-alto": "sax",
    "sax-tenor": "sax",
    "sax-baryton": "sax",
    "clarinette": "trompettes",
    "trompette": "trompettes",
    "trombone": "trombones",
    "rythmique": "rythmique",
    "chant": "chant",
}

SECTION_DEFAULTS = {
    "sax": ("Saxophones", 10),
    "trompettes": ("Trompettes & clarinette", 20),
    "trombones": ("Trombones", 30),
    "rythmique": ("Rythmique", 40),
    "chant": ("Chant", 50),
}


def forwards_consolidate_pupitres(apps, schema_editor):
    OrchestraSection = apps.get_model("planning", "OrchestraSection")
    MusicianProfile = apps.get_model("planning", "MusicianProfile")

    family_cache = {}
    for code, (name, order) in SECTION_DEFAULTS.items():
        section, created = OrchestraSection.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": order, "is_active": True},
        )
        if not created:
            updates = []
            if section.name != name:
                section.name = name
                updates.append("name")
            if section.sort_order != order:
                section.sort_order = order
                updates.append("sort_order")
            if not section.is_active:
                section.is_active = True
                updates.append("is_active")
            if updates:
                section.save(update_fields=updates)
        family_cache[code] = section

    for old_code, new_code in OLD_TO_NEW.items():
        if old_code == new_code:
            continue
        old = OrchestraSection.objects.filter(code=old_code).first()
        if old is None:
            continue
        target = family_cache[new_code]
        MusicianProfile.objects.filter(section_id=old.pk).update(section_id=target.pk)
        if old.pk != target.pk:
            old.is_active = False
            old.save(update_fields=["is_active"])

    remp_fields = (
        "poste_remplacant",
        "poste_remplacant_2",
        "poste_remplacant_3",
        "poste_remplacant_4",
        "poste_remplacant_5",
    )
    poste_section_code = {
        "alto_1": "sax",
        "alto_2": "sax",
        "tenor_1": "sax",
        "tenor_2": "sax",
        "baryton": "sax",
        "clarinette": "trompettes",
        "trompette_1": "trompettes",
        "trompette_2": "trompettes",
        "trompette_3": "trompettes",
        "trompette_4": "trompettes",
        "trombone_1": "trombones",
        "trombone_2": "trombones",
        "trombone_3": "trombones",
        "trombone_4": "trombones",
        "piano": "rythmique",
        "guitare": "rythmique",
        "basse": "rythmique",
        "batterie": "rythmique",
        "percussion": "rythmique",
        "chant": "chant",
    }
    for profile in MusicianProfile.objects.all().iterator():
        poste = profile.poste_titulaire or ""
        if not poste:
            for field in remp_fields:
                value = getattr(profile, field) or ""
                if value:
                    poste = value
                    break
        code = poste_section_code.get(poste or "")
        if not code:
            if profile.section_id is not None:
                profile.section_id = None
                profile.save(update_fields=["section_id"])
            continue
        target = family_cache[code]
        if profile.section_id != target.pk:
            profile.section_id = target.pk
            profile.save(update_fields=["section_id"])


def backwards_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("planning", "0015_dateproposal_deadline_reminder"),
    ]

    operations = [
        migrations.RunPython(forwards_consolidate_pupitres, backwards_noop),
        migrations.AlterField(
            model_name="musicianprofile",
            name="section",
            field=models.ForeignKey(
                blank=True,
                help_text="Déduit du poste titulaire, sinon du 1er poste remplaçant "
                "(pupitre = famille d’instruments).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="musicians",
                to="planning.orchestrasection",
                verbose_name="Pupitre",
            ),
        ),
    ]
