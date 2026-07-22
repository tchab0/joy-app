# Generated manually for product tours (coach marks)

import django.db.models.deletion
from django.db import migrations, models


def seed_tours(apps, schema_editor):
    ProductTour = apps.get_model("users", "ProductTour")
    ProductTourStep = apps.get_model("users", "ProductTourStep")

    from users.tour_defaults import MUSICIAN_STEPS, STAFF_STEPS

    specs = [
        ("musician", "Guide musicien", MUSICIAN_STEPS),
        ("staff", "Guide staff", STAFF_STEPS),
    ]
    for audience, title, steps in specs:
        tour, _ = ProductTour.objects.get_or_create(
            audience=audience,
            defaults={"title": title, "version": 1, "is_active": True},
        )
        if tour.steps.exists():
            continue
        ProductTourStep.objects.bulk_create(
            [
                ProductTourStep(
                    tour=tour,
                    order=s["order"],
                    anchor=s["anchor"],
                    title=s["title"],
                    body=s["body"],
                    page_path=s["page_path"],
                    open_mobile_nav=s["open_mobile_nav"],
                    scroll_footer=s["scroll_footer"],
                    is_active=True,
                )
                for s in steps
            ]
        )


def unseed_tours(apps, schema_editor):
    ProductTour = apps.get_model("users", "ProductTour")
    ProductTour.objects.filter(audience__in=["musician", "staff"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_contact_prestation_and_staff_notify"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductTour",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "audience",
                    models.CharField(
                        choices=[("musician", "Musicien"), ("staff", "Staff")],
                        max_length=20,
                        unique=True,
                        verbose_name="Audience",
                    ),
                ),
                ("title", models.CharField(max_length=120, verbose_name="Titre")),
                (
                    "version",
                    models.PositiveSmallIntegerField(
                        default=1,
                        help_text=(
                            "Incrémentez pour re-proposer le guide aux utilisateurs "
                            "qui l’avaient déjà terminé."
                        ),
                        verbose_name="Version",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="Actif"),
                ),
            ],
            options={
                "verbose_name": "guide (coach marks)",
                "verbose_name_plural": "guides (coach marks)",
                "ordering": ["audience"],
            },
        ),
        migrations.CreateModel(
            name="ProductTourStep",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("order", models.PositiveSmallIntegerField(default=0, verbose_name="Ordre")),
                (
                    "anchor",
                    models.CharField(
                        blank=True,
                        help_text=(
                            'Valeur de data-tour="…" sur la page. '
                            "Laisser vide pour un message plein écran (accueil / fin)."
                        ),
                        max_length=64,
                        verbose_name="Ancre data-tour",
                    ),
                ),
                ("title", models.CharField(max_length=160, verbose_name="Titre")),
                ("body", models.TextField(verbose_name="Texte")),
                (
                    "page_path",
                    models.CharField(
                        blank=True,
                        help_text=(
                            "Ex. /planning/ ou /compte/. Si renseigné, navigation "
                            "vers cette page avant d’afficher l’étape."
                        ),
                        max_length=200,
                        verbose_name="Chemin de page",
                    ),
                ),
                (
                    "open_mobile_nav",
                    models.BooleanField(
                        default=False,
                        help_text=(
                            "Utile pour pointer un lien de la nav principale "
                            "sur petit écran."
                        ),
                        verbose_name="Ouvrir le menu mobile",
                    ),
                ),
                (
                    "scroll_footer",
                    models.BooleanField(
                        default=False,
                        help_text="Pour les liens Administration en bas de page.",
                        verbose_name="Défiler vers le pied de page",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="Active"),
                ),
                (
                    "tour",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="steps",
                        to="users.producttour",
                        verbose_name="Guide",
                    ),
                ),
            ],
            options={
                "verbose_name": "étape de guide",
                "verbose_name_plural": "étapes de guide",
                "ordering": ["tour", "order", "pk"],
            },
        ),
        migrations.AddField(
            model_name="user",
            name="tour_musician_version",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="0 = jamais terminé. Comparé à la version du guide actif.",
                verbose_name="Version guide musicien terminée",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="tour_staff_version",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="0 = jamais terminé. Comparé à la version du guide actif.",
                verbose_name="Version guide staff terminée",
            ),
        ),
        migrations.RunPython(seed_tours, unseed_tours),
    ]
