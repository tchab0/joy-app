from pathlib import Path
import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


def media_upload_to(instance, filename: str) -> str:
    ext = Path(filename or "").suffix.lower()[:16]
    if ext not in {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".mp3",
        ".wav",
        ".ogg",
        ".flac",
        ".m4a",
        ".aac",
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".webm",
        ".pdf",
    }:
        ext = ""
    return f"medias/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"


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
    fichier = models.FileField(upload_to=media_upload_to, blank=True, null=True)
    fichier_edite = models.ImageField(
        upload_to="medias/edites/%Y/%m/",
        blank=True,
        null=True,
        help_text="Version retouchée (HD). L'original reste dans fichier jusqu'à purge J+30.",
    )
    edite_le = models.DateTimeField(blank=True, null=True)
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
        indexes = [
            models.Index(fields=["type", "publie"], name="core_media_type_publie_idx"),
            models.Index(fields=["statut", "soumis_le"], name="core_media_statut_soumis_idx"),
        ]

    def __str__(self):
        return self.titre

    @property
    def page_liee(self):
        """Libellé pour l’admin médias (objet générique rattaché)."""
        if self.content_object is None:
            return ""
        return str(self.content_object)

    @property
    def fichier_actif(self):
        """Fichier à servir / compresser : édité si présent, sinon original."""
        if self.fichier_edite:
            return self.fichier_edite
        return self.fichier

    @property
    def url_affichage(self):
        """URL publique : compressé > édité > original."""
        if self.url_compressee:
            return self.url_compressee
        actif = self.fichier_actif
        if actif:
            return actif.url
        return ""

    def source_compression(self):
        """Chemin disque à compresser (édité prioritaire)."""
        actif = self.fichier_actif
        if not actif:
            return None
        try:
            return Path(actif.path)
        except (ValueError, OSError):
            return None

    def chemin_compresse(self):
        """Chemin absolu du fichier compressé sidecar, ou None."""
        dest_dir = Path(self._media_root()) / "medias" / "compresses"

        def _photo_candidate(fieldfile):
            if not fieldfile:
                return None
            name = fieldfile.name.replace("\\", "/")
            # Déjà basculé dans compresses/ (purge) : le fichier lui-même
            if "/compresses/" in f"/{name}":
                p = Path(self._media_root()) / name
                return p if p.exists() else None
            stem = Path(name).stem
            if self.type == "photo":
                return dest_dir / f"{stem}.webp"
            if self.type == "video":
                return dest_dir / f"{stem}.mp4"
            if self.type == "audio":
                return dest_dir / f"{stem}.m4a"
            if self.type == "pdf":
                return dest_dir / f"{stem}.pdf"
            return None

        # Affichage public : compressé de l'édité s'il existe, sinon de la source
        if self.type == "photo" and self.fichier_edite:
            cand = _photo_candidate(self.fichier_edite)
            if cand and cand.exists():
                return cand

        cand = _photo_candidate(self.fichier) or _photo_candidate(self.fichier_edite)
        if cand and cand.exists():
            return cand
        return None

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
    KIND_CONTACT = "contact"
    KIND_PRESTATION = "prestation"
    KIND_CHOICES = [
        (KIND_CONTACT, "Contact"),
        (KIND_PRESTATION, "Demande de prestation"),
    ]

    STATUS_CHOICES = [
        ("new", "Nouveau"),
        ("read", "Lu"),
        ("processed", "Traité"),
        ("archived", "Archivé"),
    ]

    PROFIL_CHOICES = [
        ("particulier", "Particulier"),
        ("association", "Association"),
        ("entreprise", "Entreprise"),
        ("collectivite", "Collectivité"),
        ("agence", "Agence"),
        ("autre", "Autre"),
    ]

    TYPE_EVENEMENT_CHOICES = [
        ("concert", "Concert public"),
        ("festival", "Festival"),
        ("mariage", "Mariage / réception"),
        ("entreprise", "Entreprise / gala"),
        ("bal", "Bal / danse"),
        ("prive", "Événement privé"),
        ("autre", "Autre"),
    ]

    LIEU_TYPE_CHOICES = [
        ("interieur", "Intérieur"),
        ("exterieur", "Extérieur"),
        ("mixte", "Mixte"),
    ]

    DUREE_CHOICES = [
        ("45", "Environ 45 min"),
        ("60", "Environ 1 h"),
        ("90", "Environ 1 h 30"),
        ("120", "2 h ou plus"),
        ("indet", "À définir"),
    ]

    JAUGE_CHOICES = [
        ("50", "50"),
        ("100", "100"),
        ("150", "150"),
        ("250", "250"),
        ("500plus", "500 et +"),
    ]

    ROLE_CHOICES = [
        ("concert", "Concert assis"),
        ("cocktail", "Cocktail / fond sonore"),
        ("danse", "Danse"),
        ("ceremonie", "Cérémonie"),
        ("autre", "Autre"),
    ]

    SONO_CHOICES = [
        ("pa_complet", "Le lieu fournit un PA complet"),
        ("pa_basique", "Le lieu fournit un PA basique"),
        ("a_charge", "Sono à la charge de l’orchestre"),
        ("indet", "Je ne sais pas"),
    ]

    BUDGET_CHOICES = [
        ("indet", "À définir"),
        ("lt500", "Moins de 500 €"),
        ("500_1000", "500 – 1 000 €"),
        ("gt1000", "Plus de 1 000 €"),
    ]

    SOURCE_CHOICES = [
        ("site", "Site web"),
        ("social", "Réseaux sociaux"),
        ("bouche", "Bouche à oreille"),
        ("lieu", "Recommandation d’un lieu"),
        ("concert", "Après un concert"),
        ("autre", "Autre"),
    ]

    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        default=KIND_CONTACT,
        db_index=True,
    )
    nom = models.CharField(max_length=120)
    organisation = models.CharField(max_length=200, blank=True)
    telephone = models.CharField(max_length=40, blank=True)
    email = models.EmailField()
    profil = models.CharField(max_length=20, choices=PROFIL_CHOICES, blank=True)
    message = models.TextField(blank=True)

    type_evenement = models.CharField(
        max_length=20, choices=TYPE_EVENEMENT_CHOICES, blank=True
    )
    date_souhaitee = models.DateField(blank=True, null=True)
    date_flexible = models.BooleanField(default=False)
    date_alternative = models.DateField(blank=True, null=True)
    ville = models.CharField(max_length=120, blank=True)
    lieu_nom = models.CharField(max_length=200, blank=True)
    lieu_adresse = models.CharField(max_length=300, blank=True)
    lieu_type = models.CharField(max_length=20, choices=LIEU_TYPE_CHOICES, blank=True)
    heure_debut = models.TimeField(blank=True, null=True)
    heure_fin = models.TimeField(blank=True, null=True)
    duree_jeu = models.CharField(max_length=10, choices=DUREE_CHOICES, blank=True)
    jauge = models.CharField(max_length=20, choices=JAUGE_CHOICES, blank=True)
    role_ambiance = models.CharField(max_length=20, choices=ROLE_CHOICES, blank=True)
    sono = models.CharField(max_length=20, choices=SONO_CHOICES, blank=True)
    scene_details = models.TextField(blank=True)
    acces_logistique = models.TextField(blank=True)
    budget = models.CharField(max_length=20, choices=BUDGET_CHOICES, blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, blank=True)

    statut = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Message de contact"
        verbose_name_plural = "Messages de contact"
        ordering = ["-created_at"]

    def __str__(self):
        label = self.get_kind_display()
        return f"{label} — {self.nom} — {self.email} — {self.created_at:%d/%m/%Y %H:%M}"

    @property
    def is_prestation(self) -> bool:
        return self.kind == self.KIND_PRESTATION


class SitePage(models.Model):
    """Page publique éditable (accueil, etc.)."""

    slug = models.SlugField(unique=True, max_length=80)
    titre = models.CharField(max_length=200)
    meta_description = models.CharField(max_length=320, blank=True)
    publie = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Page du site"
        verbose_name_plural = "Pages du site"
        ordering = ["titre"]

    def __str__(self):
        return self.titre


class PageBlock(models.Model):
    """Carte / bloc de contenu d’une page, ordonnable."""

    TYPE_HERO = "hero"
    TYPE_TEXT = "text"
    TYPE_IMAGE = "image"
    TYPE_VIDEO = "video"
    TYPE_CONCERTS = "concerts"
    TYPE_CHOICES = [
        (TYPE_HERO, "En-tête (hero)"),
        (TYPE_TEXT, "Texte"),
        (TYPE_IMAGE, "Image"),
        (TYPE_VIDEO, "Vidéo"),
        (TYPE_CONCERTS, "Prochains concerts"),
    ]

    page = models.ForeignKey(SitePage, on_delete=models.CASCADE, related_name="blocks")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    titre_admin = models.CharField(
        max_length=120,
        blank=True,
        help_text="Libellé visible uniquement dans l’éditeur.",
    )
    ordre = models.PositiveIntegerField(default=0)
    visible = models.BooleanField(default=True)
    contenu = models.JSONField(default=dict, blank=True)
    media = models.ForeignKey(
        MediaItem,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="page_blocks",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Bloc de page"
        verbose_name_plural = "Blocs de page"
        ordering = ["ordre", "id"]
        indexes = [
            models.Index(fields=["page", "ordre"], name="core_pageblock_page_ordre_idx"),
        ]

    def __str__(self):
        label = self.titre_admin or self.get_type_display()
        return f"{self.page.slug} · {label}"

    def label_carte(self) -> str:
        if self.titre_admin:
            return self.titre_admin
        data = self.contenu or {}
        for key in ("titre", "title", "title_accent", "tag"):
            val = data.get(key)
            if val:
                return str(val)[:80]
        return self.get_type_display()
