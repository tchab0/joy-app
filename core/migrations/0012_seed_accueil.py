# Seed de la page d'accueil avec le contenu actuel du template

from django.db import migrations


ACCUEIL_META = (
    "Jazz Orchestra Yonnais (JOY) : big band associatif à La Roche-sur-Yon. "
    "Concerts jazz & swing en Vendée, festivals et prestations pour mariages, "
    "galas et entreprises."
)

HERO = {
    "title_accent": "J.O.Y",
    "title": "Jazz Orchestra Yonnais",
    "tag": "Big Band · La Roche-sur-Yon",
    "subtitle": (
        "Un Big Band associatif qui fait vibrer la Vendée au rythme du jazz et du swing."
    ),
    "image_alt": "Le Jazz Orchestra Yonnais sur scène",
    "image_static": "core/Joy-Cyel-home.jpg",
    "image_url": "",
    "video_url": "https://www.youtube.com/watch?v=49LYaGwuXZc",
}

ABOUT_BODY = (
    "JOY ou Jazz Orchestra Yonnais est un Big Band associatif basé à La Roche-sur-Yon, "
    "en Vendée. Passionné.e.s de jazz et de swing, nos musicien.ne.s partagent leur amour "
    "de la musique lors de concerts, festivals et événements privés.\n\n"
    "Mariages, cocktails dinatoires, soirées de gala, animations d'entreprise — "
    "le JOY met l'ambiance à chaque prestation."
)


def seed_accueil(apps, schema_editor):
    SitePage = apps.get_model("core", "SitePage")
    PageBlock = apps.get_model("core", "PageBlock")
    page, created = SitePage.objects.get_or_create(
        slug="accueil",
        defaults={
            "titre": "Accueil",
            "meta_description": ACCUEIL_META,
            "publie": True,
        },
    )
    if not created and page.blocks.exists():
        return
    if not page.meta_description:
        page.meta_description = ACCUEIL_META
        page.save(update_fields=["meta_description"])

    PageBlock.objects.create(
        page=page,
        type="hero",
        titre_admin="En-tête",
        ordre=0,
        visible=True,
        contenu=HERO,
    )
    PageBlock.objects.create(
        page=page,
        type="concerts",
        titre_admin="Prochains concerts",
        ordre=1,
        visible=True,
        contenu={"titre": "Prochains concerts", "limit": 3},
    )
    PageBlock.objects.create(
        page=page,
        type="text",
        titre_admin="Le Big Band",
        ordre=2,
        visible=True,
        contenu={
            "titre": "Le Big Band",
            "body": ABOUT_BODY,
            "cta_label": "Demande de prestation",
            "cta_url": "/contact/?mode=prestation",
        },
    )


def unseed_accueil(apps, schema_editor):
    SitePage = apps.get_model("core", "SitePage")
    SitePage.objects.filter(slug="accueil").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_sitepage_pageblock"),
    ]

    operations = [
        migrations.RunPython(seed_accueil, unseed_accueil),
    ]
