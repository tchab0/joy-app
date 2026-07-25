from pathlib import Path

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class ExternalLink(models.Model):
    titre = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    url = models.URLField()
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Lien externe"
        verbose_name_plural = "Liens externes"

    def __str__(self):
        return self.titre


class EvenementMedia(models.Model):
    nom = models.CharField(max_length=200)
    date = models.DateField(blank=True, null=True)
    lieu = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Événement média"
        verbose_name_plural = "Événements média"
        ordering = ["-date", "nom"]

    def __str__(self):
        if self.date:
            return f"{self.nom} ({self.date:%d/%m/%Y})"
        return self.nom


class MediaItem(models.Model):
    TYPE_CHOICES = [
        ("photo", "Photo"),
        ("video", "Vidéo"),
        ("audio", "Audio"),
        ("pdf", "PDF"),
    ]

    STATUT_CHOICES = [
        ("en_attente", "En attente"),
        ("en_cours", "Compression en cours"),
        ("publie", "Publié"),
        ("refuse", "Refusé"),
    ]

    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    titre = models.CharField(max_length=200)
    fichier = models.FileField(upload_to="medias/%Y/%m/", blank=True, null=True)
    url_externe = models.URLField(blank=True)
    miniature = models.ImageField(upload_to="medias/thumbs/%Y/%m/", blank=True, null=True)
    evenement = models.ForeignKey(
        EvenementMedia,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="items",
    )
    ordre = models.PositiveIntegerField(default=0)
    publie = models.BooleanField(default=False)
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default="en_attente")
    note_admin = models.TextField(blank=True)
    soumis_par_nom = models.CharField(max_length=120, blank=True)
    soumis_par_email = models.EmailField(blank=True)
    soumis_le = models.DateTimeField(default=timezone.now)

    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, blank=True, null=True)
    object_id = models.PositiveIntegerField(blank=True, null=True)
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        verbose_name = "Média"
        verbose_name_plural = "Médias"
        ordering = ["ordre", "id"]

    def __str__(self):
        return self.titre

    @property
    def fichier_actif(self):
        return self.fichier

    def chemin_compresse_destination(self):
        """Chemin unique réservé à la version compressée de ce média."""
        if not self.fichier:
            return None

        source = Path(self.fichier.name)
        if source.parent == Path("medias/compresses"):
            return Path(self.fichier.path)

        if not self.pk:
            return None

        extensions = {
            "photo": ".webp",
            "video": ".mp4",
            "audio": ".m4a",
            "pdf": ".pdf",
        }
        extension = extensions.get(self.type)
        if not extension:
            return None

        dest_dir = Path(self._media_root()) / "medias" / "compresses"
        return dest_dir / f"{self.pk}_{source.stem}{extension}"

    def chemin_compresse(self):
        """Chemin absolu du fichier compressé sidecar, ou None."""
        destination = self.chemin_compresse_destination()
        return destination if destination and destination.exists() else None

    def chemin_compresse_relatif(self):
        abs_path = self.chemin_compresse()
        if not abs_path:
            return ""
        return abs_path.relative_to(Path(self._media_root())).as_posix()

    @property
    def est_compresse(self):
        return self.chemin_compresse() is not None

    @property
    def url_compressee(self):
        rel = self.chemin_compresse_relatif()
        if not rel:
            return ""
        return f"{self._media_url()}{rel}"

    @staticmethod
    def _media_root():
        from django.conf import settings
        return settings.MEDIA_ROOT

    @staticmethod
    def _media_url():
        from django.conf import settings
        return settings.MEDIA_URL


class MediaVote(models.Model):
    media = models.ForeignKey(MediaItem, on_delete=models.CASCADE, related_name="votes")
    session_key = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Vote média"
        verbose_name_plural = "Votes médias"
        constraints = [
            models.UniqueConstraint(fields=["media", "session_key"], name="unique_vote_par_session")
        ]

    def __str__(self):
        return f"{self.media_id} / {self.session_key}"


class ContactMessage(models.Model):
    STATUS_CHOICES = [
        ("new", "Nouveau"),
        ("read", "Lu"),
        ("processed", "Traité"),
        ("archived", "Archivé"),
    ]

    nom = models.CharField(max_length=120)
    telephone = models.CharField(max_length=40, blank=True)
    email = models.EmailField()
    message = models.TextField()
    statut = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Message de contact"
        verbose_name_plural = "Messages de contact"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.nom} — {self.email} — {self.created_at:%d/%m/%Y %H:%M}"
