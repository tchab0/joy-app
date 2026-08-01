from __future__ import annotations

from django.conf import settings
from django.db import models


class UsageEvent(models.Model):
    """Trace légère d’usage des espaces authentifiés (rétention limitée)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_events",
        verbose_name="Utilisateur",
    )
    name = models.CharField(
        "Événement",
        max_length=64,
        db_index=True,
        help_text="Ex. planning.view, repertoire.pdf, chat.view",
    )
    path = models.CharField("Chemin", max_length=300, blank=True)
    created_at = models.DateTimeField("Date", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "événement d’usage"
        verbose_name_plural = "événements d’usage"
        indexes = [
            models.Index(fields=["name", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} @ {self.created_at:%Y-%m-%d %H:%M}"


class PublicPageView(models.Model):
    """Vue de page publique (anonyme) pour mesurer l’audience du site."""

    path = models.CharField("Chemin", max_length=300, db_index=True)
    session_key = models.CharField(
        "Clé de session",
        max_length=40,
        blank=True,
        db_index=True,
        help_text="Identifiant de session Django (pas d’IP stockée).",
    )
    created_at = models.DateTimeField("Date", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "vue page publique"
        verbose_name_plural = "vues pages publiques"
        indexes = [
            models.Index(fields=["created_at", "path"]),
            models.Index(fields=["session_key", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.path} @ {self.created_at:%Y-%m-%d %H:%M}"
