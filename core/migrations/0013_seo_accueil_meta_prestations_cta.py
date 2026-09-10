"""SEO : meta accueil + CTA Big Band → page Prestations."""

from django.db import migrations

ACCUEIL_META = (
    "Jazz Orchestra Yonnais (JOY) — big band à La Roche-sur-Yon. "
    "Concerts jazz & swing en Vendée, prestations pour mariages, galas et entreprises."
)


def forwards(apps, schema_editor):
    SitePage = apps.get_model("core", "SitePage")
    PageBlock = apps.get_model("core", "PageBlock")

    page = SitePage.objects.filter(slug="accueil").first()
    if page:
        page.meta_description = ACCUEIL_META
        page.save(update_fields=["meta_description"])

    for block in PageBlock.objects.filter(page__slug="accueil", type="text"):
        contenu = dict(block.contenu or {})
        url = (contenu.get("cta_url") or "").rstrip("/")
        if url == "/contact/?mode=prestation" or contenu.get("cta_label") == "Demande de prestation":
            contenu["cta_url"] = "/prestations/"
            if contenu.get("cta_label") == "Demande de prestation":
                contenu["cta_label"] = "Prestations & devis"
            block.contenu = contenu
            block.save(update_fields=["contenu"])


def backwards(apps, schema_editor):
    SitePage = apps.get_model("core", "SitePage")
    PageBlock = apps.get_model("core", "PageBlock")

    page = SitePage.objects.filter(slug="accueil").first()
    if page and page.meta_description.startswith("Jazz Orchestra Yonnais (JOY) — big band"):
        page.meta_description = (
            "Jazz Orchestra Yonnais (JOY) : big band associatif à La Roche-sur-Yon. "
            "Concerts jazz & swing en Vendée, festivals et prestations pour mariages, "
            "galas et entreprises."
        )
        page.save(update_fields=["meta_description"])

    for block in PageBlock.objects.filter(page__slug="accueil", type="text"):
        contenu = dict(block.contenu or {})
        if contenu.get("cta_url") == "/prestations/":
            contenu["cta_url"] = "/contact/?mode=prestation"
            if contenu.get("cta_label") == "Prestations & devis":
                contenu["cta_label"] = "Demande de prestation"
            block.contenu = contenu
            block.save(update_fields=["contenu"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_seed_accueil"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
