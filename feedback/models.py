from __future__ import annotations

from django.conf import settings
from django.db import models


class PageFeedback(models.Model):
    """Retour utilisateur sur une page (bug, confort, fonctionnalité manquante)."""

    CATEGORY_BUG = "BUG"
    CATEGORY_COMFORT = "COMFORT"
    CATEGORY_MISSING_FEATURE = "MISSING_FEATURE"
    CATEGORY_CHOICES = (
        (CATEGORY_BUG, "Bug"),
        (CATEGORY_COMFORT, "Confort de la vue"),
        (CATEGORY_MISSING_FEATURE, "Fonctionnalité manquante"),
    )

    STATUS_NEW = "NEW"
    STATUS_READ = "READ"
    STATUS_CHOICES = (
        (STATUS_NEW, "Nouveau"),
        (STATUS_READ, "Lu"),
    )

    IMPORTANCE_CHOICES = (
        (1, "1 — Pas important"),
        (2, "2"),
        (3, "3"),
        (4, "4"),
        (5, "5 — Très important"),
    )

    ADMIN_PRIORITY_CHOICES = (
        (1, "1 — Faible"),
        (2, "2"),
        (3, "3"),
        (4, "4"),
        (5, "5 — Urgent"),
    )

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="page_feedbacks",
        verbose_name="Auteur",
    )
    category = models.CharField("Type de retour", max_length=20, choices=CATEGORY_CHOICES)
    importance = models.PositiveSmallIntegerField(
        "Importance",
        choices=IMPORTANCE_CHOICES,
        null=True,
        blank=True,
        help_text="Importance affichée (1 à 5), arrondie à partir du score bayésien.",
    )
    importance_score = models.DecimalField(
        "Score d'importance",
        max_digits=6,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Score bayésien (note + effectif des votes) pour le tri.",
    )
    admin_priority = models.PositiveSmallIntegerField(
        "Priorité admin",
        choices=ADMIN_PRIORITY_CHOICES,
        null=True,
        blank=True,
        help_text="Urgence définie par l'administrateur (1 à 5).",
    )
    message = models.TextField("Message")
    page_url = models.CharField("Page concernée", max_length=500)
    page_title = models.CharField("Titre de la page", max_length=200, blank=True)
    page_context = models.TextField("Contexte page (JSON)", blank=True)
    status = models.CharField(
        "Statut",
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_NEW,
    )
    created_at = models.DateTimeField("Date", auto_now_add=True)
    read_at = models.DateTimeField("Lu le", null=True, blank=True)
    read_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="page_feedbacks_marked_read",
        verbose_name="Lu par",
    )
    author_notified_at = models.DateTimeField("Auteur informé le", null=True, blank=True)
    author_notified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="page_feedbacks_author_notified",
        verbose_name="Informé par",
    )
    author_response_seen_at = models.DateTimeField(
        "Réponse lue par l'auteur le", null=True, blank=True
    )
    treated_at = models.DateTimeField("Traité le", null=True, blank=True)
    treated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="page_feedbacks_marked_treated",
        verbose_name="Traité par",
    )
    in_progress_at = models.DateTimeField("En cours le", null=True, blank=True)
    in_progress_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="page_feedbacks_marked_in_progress",
        verbose_name="En cours par",
    )
    snoozed_until = models.DateTimeField("Reporté jusqu’au", null=True, blank=True)
    snoozed_at = models.DateTimeField("Reporté le", null=True, blank=True)
    snoozed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="page_feedbacks_snoozed",
        verbose_name="Reporté par",
    )
    vote_formulation = models.TextField(
        "Formulation au vote",
        blank=True,
        help_text="Texte reformulé par l'administrateur soumis au vote.",
    )
    vote_roles = models.JSONField(
        "Rôles éligibles au vote",
        default=list,
        blank=True,
        help_text="Liste de rôles JOY (musician, association_member, staff).",
    )
    vote_opened_at = models.DateTimeField("Vote ouvert le", null=True, blank=True)
    vote_opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="page_feedbacks_votes_opened",
        verbose_name="Vote ouvert par",
    )
    vote_closed_at = models.DateTimeField("Vote clos le", null=True, blank=True)
    vote_closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="page_feedbacks_votes_closed",
        verbose_name="Vote clos par",
    )

    class Meta:
        verbose_name = "Retour utilisateur"
        verbose_name_plural = "Retours utilisateurs"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_category_display()} — {self.author} ({self.created_at:%d/%m/%Y})"


class PageFeedbackVote(models.Model):
    """Vote pour ou contre une proposition reformulée par l'administrateur."""

    VOTE_FOR = "FOR"
    VOTE_AGAINST = "AGAINST"
    CHOICE_CHOICES = (
        (VOTE_FOR, "Pour"),
        (VOTE_AGAINST, "Contre"),
    )

    feedback = models.ForeignKey(
        PageFeedback,
        on_delete=models.CASCADE,
        related_name="votes",
        verbose_name="Retour",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="page_feedback_votes",
        verbose_name="Utilisateur",
    )
    choice = models.CharField("Choix", max_length=10, choices=CHOICE_CHOICES)
    created_at = models.DateTimeField("Date", auto_now_add=True)

    class Meta:
        verbose_name = "Vote sur une proposition"
        verbose_name_plural = "Votes sur les propositions"
        constraints = [
            models.UniqueConstraint(
                fields=("feedback", "user"),
                name="feedback_pagefeedbackvote_feedback_user_uniq",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} → {self.feedback_id} ({self.get_choice_display()})"


class PageFeedbackRating(models.Model):
    """Importance accordée par un utilisateur à un retour existant."""

    feedback = models.ForeignKey(
        PageFeedback,
        on_delete=models.CASCADE,
        related_name="ratings",
        verbose_name="Retour",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="page_feedback_ratings",
        verbose_name="Utilisateur",
    )
    importance = models.PositiveSmallIntegerField(
        "Importance",
        choices=PageFeedback.IMPORTANCE_CHOICES,
    )
    created_at = models.DateTimeField("Date", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        verbose_name = "Soutien sur un retour"
        verbose_name_plural = "Soutiens sur les retours"
        constraints = [
            models.UniqueConstraint(
                fields=("feedback", "user"),
                name="feedback_pagefeedbackrating_feedback_user_uniq",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} → {self.feedback_id} ({self.importance}/5)"
