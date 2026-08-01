from __future__ import annotations

from django.conf import settings
from django.db import models


class RehearsalPlan(models.Model):
    """Feuille de route d’une répétition (liée à un Event type Répétition)."""

    event = models.OneToOneField(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="rehearsal_plan",
        verbose_name="Événement",
    )
    notes = models.TextField(
        "Notes générales",
        blank=True,
        help_text="Consignes, focus de la séance…",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_rehearsal_plans",
        verbose_name="Mis à jour par",
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Mis à jour le", auto_now=True)

    class Meta:
        verbose_name = "feuille de route"
        verbose_name_plural = "feuilles de route"
        ordering = ["-event__date_debut"]

    def __str__(self) -> str:
        return f"Feuille de route — {self.event}"


class RehearsalItem(models.Model):
    """Morceau travaillé pendant une répétition."""

    plan = models.ForeignKey(
        RehearsalPlan,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Feuille de route",
    )
    piece = models.ForeignKey(
        "repertoire.Piece",
        on_delete=models.CASCADE,
        related_name="rehearsal_items",
        verbose_name="Morceau",
    )
    position = models.PositiveSmallIntegerField("Ordre", default=1)
    note = models.CharField(
        "Note",
        max_length=300,
        blank=True,
        help_text="Ex. intro + chorus sax",
    )

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "morceau de répétition"
        verbose_name_plural = "morceaux de répétition"
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "piece"],
                name="unique_rehearsal_item_per_plan_piece",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.position}. {self.piece}"
