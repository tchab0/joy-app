# Generated manually for SitePage / PageBlock CMS

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_security_perf_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="SitePage",
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
                ("slug", models.SlugField(max_length=80, unique=True)),
                ("titre", models.CharField(max_length=200)),
                ("meta_description", models.CharField(blank=True, max_length=320)),
                ("publie", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Page du site",
                "verbose_name_plural": "Pages du site",
                "ordering": ["titre"],
            },
        ),
        migrations.CreateModel(
            name="PageBlock",
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
                    "type",
                    models.CharField(
                        choices=[
                            ("hero", "En-tête (hero)"),
                            ("text", "Texte"),
                            ("image", "Image"),
                            ("video", "Vidéo"),
                            ("concerts", "Prochains concerts"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "titre_admin",
                    models.CharField(
                        blank=True,
                        help_text="Libellé visible uniquement dans l’éditeur.",
                        max_length=120,
                    ),
                ),
                ("ordre", models.PositiveIntegerField(default=0)),
                ("visible", models.BooleanField(default=True)),
                ("contenu", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "media",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="page_blocks",
                        to="core.mediaitem",
                    ),
                ),
                (
                    "page",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blocks",
                        to="core.sitepage",
                    ),
                ),
            ],
            options={
                "verbose_name": "Bloc de page",
                "verbose_name_plural": "Blocs de page",
                "ordering": ["ordre", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="pageblock",
            index=models.Index(
                fields=["page", "ordre"], name="core_pageblock_page_ordre_idx"
            ),
        ),
    ]
