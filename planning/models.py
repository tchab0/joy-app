from django.conf import settings
from django.db import models


class ParticipationStatus(models.Model):
    code = models.SlugField(
        max_length=50,
        unique=True,
        verbose_name="Code",
        help_text="Clé technique stable (ex : invited, confirmed, declined)",
    )
    label = models.CharField(
        max_length=100,
        verbose_name="Libellé",
    )
    color_token = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Token couleur",
        help_text="Ex : success, warning, danger, neutral",
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="Ordre d’affichage",
    )
    is_active = models.BooleanField(default=True, verbose_name="Actif")

    class Meta:
        ordering = ["sort_order", "label"]
        verbose_name = "Statut de participation"
        verbose_name_plural = "Statuts de participation"

    def __str__(self):
        return self.label


class EventParticipation(models.Model):
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="participations",
        verbose_name="Concert",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="event_participations",
        verbose_name="Musicien",
    )
    status = models.ForeignKey(
        "planning.ParticipationStatus",
        on_delete=models.PROTECT,
        related_name="participations",
        verbose_name="Statut",
    )
    comment = models.TextField(
        blank=True,
        verbose_name="Commentaire",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        ordering = ["event__date_debut", "user__last_name", "user__first_name"]
        verbose_name = "Participation concert"
        verbose_name_plural = "Participations concerts"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "user"],
                name="unique_event_participation_per_user",
            )
        ]

    def __str__(self):
        return f"{self.event} – {self.user}"
