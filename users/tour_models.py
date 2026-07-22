"""Guides (coach marks) première connexion — éditables en admin."""

from __future__ import annotations

from django.db import models


class ProductTour(models.Model):
    """Parcours guidé (musicien ou staff)."""

    class Audience(models.TextChoices):
        MUSICIAN = "musician", "Musicien"
        STAFF = "staff", "Staff"

    audience = models.CharField(
        "Audience",
        max_length=20,
        choices=Audience.choices,
        unique=True,
    )
    title = models.CharField("Titre", max_length=120)
    version = models.PositiveSmallIntegerField(
        "Version",
        default=1,
        help_text=(
            "Incrémentez pour re-proposer le guide aux utilisateurs "
            "qui l’avaient déjà terminé."
        ),
    )
    is_active = models.BooleanField("Actif", default=True)

    class Meta:
        verbose_name = "guide (coach marks)"
        verbose_name_plural = "guides (coach marks)"
        ordering = ["audience"]

    def __str__(self) -> str:
        return f"{self.get_audience_display()} v{self.version}"


class ProductTourStep(models.Model):
    """Étape d’un guide — texte et cible modifiables en admin."""

    tour = models.ForeignKey(
        ProductTour,
        on_delete=models.CASCADE,
        related_name="steps",
        verbose_name="Guide",
    )
    order = models.PositiveSmallIntegerField("Ordre", default=0)
    anchor = models.CharField(
        "Ancre data-tour",
        max_length=64,
        blank=True,
        help_text=(
            "Valeur de data-tour=\"…\" sur la page. "
            "Laisser vide pour un message plein écran (accueil / fin)."
        ),
    )
    title = models.CharField("Titre", max_length=160)
    body = models.TextField("Texte")
    page_path = models.CharField(
        "Chemin de page",
        max_length=200,
        blank=True,
        help_text=(
            "Ex. /planning/ ou /compte/. Si renseigné, navigation "
            "vers cette page avant d’afficher l’étape."
        ),
    )
    open_mobile_nav = models.BooleanField(
        "Ouvrir le menu mobile",
        default=False,
        help_text="Utile pour pointer un lien de la nav principale sur petit écran.",
    )
    scroll_footer = models.BooleanField(
        "Défiler vers le pied de page",
        default=False,
        help_text="Pour les liens Administration en bas de page.",
    )
    is_active = models.BooleanField("Active", default=True)

    class Meta:
        verbose_name = "étape de guide"
        verbose_name_plural = "étapes de guide"
        ordering = ["tour", "order", "pk"]

    def __str__(self) -> str:
        return f"{self.tour.audience} #{self.order} — {self.title}"
