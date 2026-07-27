from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone


class ChatRoom(models.Model):
    class Kind(models.TextChoices):
        ORCHESTRA = "orchestra", "Orchestre"
        EVENT = "event", "Événement"
        PIECE = "piece", "Morceau"
        STAFF = "staff", "Staff"

    kind = models.CharField(
        "Type",
        max_length=20,
        choices=Kind.choices,
        db_index=True,
    )
    title = models.CharField("Titre", max_length=200)
    event = models.OneToOneField(
        "events.Event",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="chat_room",
        verbose_name="Événement",
    )
    piece = models.OneToOneField(
        "repertoire.Piece",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="chat_room",
        verbose_name="Morceau",
    )
    is_active = models.BooleanField("Actif", default=True)
    created_at = models.DateTimeField("Créé le", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "salon"
        verbose_name_plural = "salons"
        constraints = [
            models.UniqueConstraint(
                fields=["kind"],
                condition=models.Q(kind="orchestra"),
                name="unique_orchestra_chat_room",
            ),
            models.UniqueConstraint(
                fields=["kind"],
                condition=models.Q(kind="staff"),
                name="unique_staff_chat_room",
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def channel_group(self) -> str:
        return f"chat.room.{self.pk}"


class ChatMembership(models.Model):
    room = models.ForeignKey(
        ChatRoom,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name="Salon",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_memberships",
        verbose_name="Utilisateur",
    )
    subscribed = models.BooleanField(
        "Alertes (digest)",
        default=True,
        help_text="Reçoit un digest (push ou e-mail) des nouveaux messages.",
    )
    joined_at = models.DateTimeField("Rejoint le", auto_now_add=True)
    left_at = models.DateTimeField("Quitté le", null=True, blank=True)
    last_read_at = models.DateTimeField("Dernière lecture", null=True, blank=True)
    last_digested_message_id = models.PositiveBigIntegerField(
        "Dernier message digéré",
        default=0,
        help_text="ID du dernier message inclus dans un digest d’alertes.",
    )

    class Meta:
        ordering = ["room_id", "user_id"]
        verbose_name = "appartenance salon"
        verbose_name_plural = "appartenances salon"
        constraints = [
            models.UniqueConstraint(
                fields=["room", "user"],
                name="unique_chat_membership",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.room}"

    @property
    def is_active_member(self) -> bool:
        return self.left_at is None

    def leave(self) -> None:
        if self.left_at is None:
            self.left_at = timezone.now()
            self.subscribed = False
            self.save(update_fields=["left_at", "subscribed"])

    def rejoin(self, *, subscribed: bool | None = None) -> None:
        self.left_at = None
        if subscribed is not None:
            self.subscribed = subscribed
        self.save(
            update_fields=["left_at", "subscribed"]
            if subscribed is not None
            else ["left_at"]
        )


class ChatMessage(models.Model):
    class Kind(models.TextChoices):
        NORMAL = "normal", "Message"
        POLL_LAUNCH = "poll_launch", "Lancement de sondage"
        SYSTEM = "system", "Système"

    room = models.ForeignKey(
        ChatRoom,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Salon",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="chat_messages",
        verbose_name="Auteur",
    )
    kind = models.CharField(
        "Type",
        max_length=20,
        choices=Kind.choices,
        default=Kind.NORMAL,
        db_index=True,
    )
    body = models.TextField("Message", blank=True)
    related_proposal = models.ForeignKey(
        "planning.DateProposal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_messages",
        verbose_name="Sondage lié",
    )
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replies",
        verbose_name="Réponse à",
    )
    created_at = models.DateTimeField("Envoyé le", auto_now_add=True, db_index=True)
    edited_at = models.DateTimeField("Modifié le", null=True, blank=True)
    deleted_at = models.DateTimeField("Supprimé le", null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "message"
        verbose_name_plural = "messages"
        indexes = [
            models.Index(
                fields=["room", "created_at"],
                name="chat_msg_room_created_idx",
            ),
            models.Index(
                fields=["room", "deleted_at", "created_at"],
                name="chat_msg_room_del_created_idx",
            ),
        ]

    def __str__(self) -> str:
        preview = (self.body or "")[:40]
        return f"#{self.pk} {preview}"

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def is_highlight(self) -> bool:
        return self.kind == self.Kind.POLL_LAUNCH


def chat_attachment_upload_to(instance: "ChatAttachment", filename: str) -> str:
    ext = Path(filename or "").suffix.lower()[:16]
    if ext not in {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".pdf",
        ".mp3",
        ".wav",
        ".ogg",
        ".m4a",
        ".mp4",
        ".webm",
        ".txt",
        ".doc",
        ".docx",
    }:
        ext = ""
    return f"chat/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"


class ChatAttachment(models.Model):
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="Message",
    )
    file = models.FileField("Fichier", upload_to=chat_attachment_upload_to)
    original_name = models.CharField("Nom original", max_length=255)
    content_type = models.CharField("Type MIME", max_length=120, blank=True)
    size = models.PositiveBigIntegerField("Taille (octets)", default=0)
    created_at = models.DateTimeField("Ajouté le", auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "pièce jointe"
        verbose_name_plural = "pièces jointes"

    def __str__(self) -> str:
        return self.original_name

    @property
    def is_image(self) -> bool:
        ct = (self.content_type or "").lower()
        if not ct.startswith("image/"):
            return False
        # Never treat SVG as displayable image (XSS vector).
        return ct != "image/svg+xml"

    @property
    def is_pdf(self) -> bool:
        return self.content_type == "application/pdf"


class ChatMessageReaction(models.Model):
    """
    Réaction d'un participant sur un message.
    - up : pouce levé (compteur visible pour tous)
    - down : pouce baissé (masque le message uniquement pour l'auteur de la réaction)
    """

    class Value(models.TextChoices):
        UP = "up", "Pouce levé"
        DOWN = "down", "Pouce baissé"

    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name="reactions",
        verbose_name="Message",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_reactions",
        verbose_name="Utilisateur",
    )
    value = models.CharField(
        "Réaction",
        max_length=8,
        choices=Value.choices,
        db_index=True,
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        verbose_name = "réaction chat"
        verbose_name_plural = "réactions chat"
        constraints = [
            models.UniqueConstraint(
                fields=["message", "user"],
                name="unique_chat_message_reaction",
            ),
        ]
        indexes = [
            models.Index(
                fields=["message", "value"],
                name="chat_react_msg_value_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.value} on #{self.message_id}"
