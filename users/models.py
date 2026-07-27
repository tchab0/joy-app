from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """Compte unique pour musiciens, adhérents et staff."""

    class Preferred2FA(models.TextChoices):
        APP = "app", "Application d’authentification"
        NOTIFICATION = "sms", "Notification"
        EMAIL = "email", "E-mail"

    phone = models.CharField(
        "Téléphone",
        max_length=20,
        blank=True,
        db_index=True,
        help_text="Format international recommandé (ex. +33612345678).",
    )
    phone_verified = models.BooleanField("Téléphone vérifié", default=False)
    email_verified = models.BooleanField("E-mail vérifié", default=False)

    is_musician = models.BooleanField(
        "Musicien de l’orchestre",
        default=False,
        db_index=True,
        help_text="Accès planning et outils musiciens.",
    )
    is_association_member = models.BooleanField(
        "Membre de l’association",
        default=False,
        db_index=True,
        help_text="Accès espace adhérents.",
    )
    membership_expires_at = models.DateField(
        "Fin d’adhésion",
        null=True,
        blank=True,
    )

    totp_secret = models.CharField(
        "Secret TOTP",
        max_length=64,
        blank=True,
        help_text="Secret base32 pour l’application d’authentification.",
    )
    totp_enabled = models.BooleanField("2FA application activée", default=False)
    two_factor_enabled = models.BooleanField(
        "Double authentification obligatoire",
        default=False,
        help_text="Après le mot de passe, exige un second facteur (app, notification ou e-mail).",
    )
    preferred_2fa_channel = models.CharField(
        "Canal 2FA préféré",
        max_length=10,
        choices=Preferred2FA.choices,
        default=Preferred2FA.EMAIL,
    )
    chat_auto_subscribe = models.BooleanField(
        "Abonnement auto aux salons chat",
        default=True,
        help_text=(
            "À la création d’un événement, s’abonner automatiquement "
            "aux alertes (push ou e-mail) du salon associé."
        ),
    )
    notify_contact_messages = models.BooleanField(
        "Alertes messages de contact",
        default=True,
        help_text=(
            "Recevoir une notification (push ou e-mail) lorsqu’un message "
            "de contact ou une demande de prestation arrive."
        ),
    )

    tour_musician_version = models.PositiveSmallIntegerField(
        "Version guide musicien terminée",
        default=0,
        help_text="0 = jamais terminé. Comparé à la version du guide actif.",
    )
    tour_staff_version = models.PositiveSmallIntegerField(
        "Version guide staff terminée",
        default=0,
        help_text="0 = jamais terminé. Comparé à la version du guide actif.",
    )
    dismissed_page_leads = models.JSONField(
        "Aides de page masquées",
        default=list,
        blank=True,
        help_text="Clés des textes d’aide masqués en haut de page.",
    )

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        permissions = [
            ("access_planning", "Peut accéder au planning musiciens"),
            ("access_member_area", "Peut accéder à l’espace adhérents"),
        ]

    def __str__(self) -> str:
        full = self.get_full_name().strip()
        return full or self.username

    @property
    def membership_active(self) -> bool:
        if not self.is_association_member:
            return False
        if self.membership_expires_at is None:
            return True
        return self.membership_expires_at >= timezone.localdate()

    def clear_role_cache(self) -> None:
        for attr in (
            "_cached_roles",
            "_cached_perm_codes",
            "_perm_cache",
            "_user_perm_cache",
            "_group_perm_cache",
        ):
            if hasattr(self, attr):
                delattr(self, attr)


class AuthChallenge(models.Model):
    """Défi OTP pour connexion, 2FA ou vérification de contact."""

    class Purpose(models.TextChoices):
        LOGIN = "login", "Connexion"
        TWO_FACTOR = "2fa", "Double authentification"
        VERIFY_EMAIL = "verify_email", "Vérification e-mail"
        VERIFY_PHONE = "verify_phone", "Vérification téléphone"

    class Channel(models.TextChoices):
        EMAIL = "email", "E-mail"
        NOTIFICATION = "sms", "Notification"
        APP = "app", "Application"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="auth_challenges",
        verbose_name="Utilisateur",
    )
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    code_hash = models.CharField(max_length=128)
    destination = models.CharField(
        max_length=254,
        blank=True,
        help_text="E-mail ou numéro ciblé (masqué côté UI).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    session_key = models.CharField(max_length=40, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "défi d’authentification"
        verbose_name_plural = "défis d’authentification"
        indexes = [
            models.Index(fields=["user", "purpose", "consumed_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.purpose}/{self.channel} → {self.user_id}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    @property
    def is_usable(self) -> bool:
        return (
            not self.is_consumed
            and not self.is_expired
            and self.attempts < self.max_attempts
        )


class PushSubscription(models.Model):
    """Abonnement Web Push d’un appareil / navigateur."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
        verbose_name="Utilisateur",
    )
    endpoint = models.URLField("Endpoint", max_length=500, unique=True)
    p256dh = models.CharField("Clé p256dh", max_length=200)
    auth = models.CharField("Clé auth", max_length=100)
    user_agent = models.CharField("User-Agent", max_length=300, blank=True)
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Mis à jour le", auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "abonnement push"
        verbose_name_plural = "abonnements push"

    def __str__(self) -> str:
        return f"PushSubscription({self.user_id}, {self.endpoint[:48]}…)"


class UserNotification(models.Model):
    """Notification in-app (historique + non-lu / non-répondu), en plus du push / e-mail."""

    class RelatedType(models.TextChoices):
        EVENT = "event", "Événement"
        PARTICIPATION = "participation", "Participation"
        PROPOSAL = "proposal", "Sondage"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Destinataire",
    )
    title = models.CharField("Titre", max_length=200)
    body = models.TextField("Message")
    url = models.CharField(
        "Lien",
        max_length=500,
        blank=True,
        help_text="Chemin relatif ou URL absolue (ex. /planning/).",
    )
    created_at = models.DateTimeField("Créée le", auto_now_add=True, db_index=True)
    read_at = models.DateTimeField("Lue le", null=True, blank=True, db_index=True)
    requires_response = models.BooleanField(
        "Attend une réponse",
        default=False,
        db_index=True,
        help_text="Invitation, sondage, relance… — distinct de la lecture.",
    )
    responded_at = models.DateTimeField(
        "Répondue le",
        null=True,
        blank=True,
        db_index=True,
    )
    related_type = models.CharField(
        "Objet lié",
        max_length=20,
        blank=True,
        choices=RelatedType.choices,
        help_text="Pour marquer « répondue » quand le musicien agit.",
    )
    related_id = models.PositiveIntegerField(
        "ID objet lié",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "notification"
        verbose_name_plural = "notifications"
        indexes = [
            models.Index(fields=["user", "read_at", "-created_at"]),
            models.Index(
                fields=["requires_response", "responded_at", "-created_at"]
            ),
            models.Index(fields=["related_type", "related_id", "user"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} → {self.user_id}"

    @property
    def is_unread(self) -> bool:
        return self.read_at is None

    @property
    def is_unanswered(self) -> bool:
        return self.requires_response and self.responded_at is None

    def mark_read(self) -> bool:
        """Marque comme lue. Retourne True si un changement a été fait."""
        if self.read_at is not None:
            return False
        self.read_at = timezone.now()
        self.save(update_fields=["read_at"])
        from users.notify import invalidate_nav_banner

        invalidate_nav_banner(self.user)
        return True

    def mark_responded(self) -> bool:
        """Marque comme répondue. Retourne True si un changement a été fait."""
        if not self.requires_response or self.responded_at is not None:
            return False
        self.responded_at = timezone.now()
        self.save(update_fields=["responded_at"])
        return True


# Guides coach marks (éditables en admin) — importés pour découverte Django.
from .tour_models import ProductTour, ProductTourStep  # noqa: E402, F401
