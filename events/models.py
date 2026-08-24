from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Venue(models.Model):
    nom = models.CharField(max_length=200)
    adresse = models.CharField(max_length=300, blank=True)
    ville     = models.CharField(max_length=100)
    latitude  = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        verbose_name = "Lieu"
        ordering = ["ville", "nom"]

    def __str__(self):
        return f"{self.nom} — {self.ville}"

    @property
    def has_coords(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class Organisme(models.Model):
    """Organisateur mémorisé (mairie, festival, association…) pour saisie typeahead."""

    nom = models.CharField(max_length=200, unique=True)
    url_site = models.URLField(
        "Site web",
        blank=True,
        help_text="Page web de l’organisme (lien sur le nom en affichage public).",
    )

    class Meta:
        verbose_name = "Organisme"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class EventType(models.Model):
    nom = models.CharField(max_length=100)
    is_rehearsal = models.BooleanField(
        "Répétition",
        default=False,
        help_text="Coché = ce type est une répétition (calendrier, absences, contact masqué).",
    )

    class Meta:
        verbose_name = "Type d'événement"

    def __str__(self):
        return self.nom


class Event(models.Model):
    class Statut(models.TextChoices):
        CONFIRME  = 'confirme',  'Confirmé'
        TENTATIVE = 'tentative', 'Date à confirmer'
        ANNULE    = 'annule',    'Annulé'

    titre       = models.CharField(max_length=300)
    slug        = models.SlugField(
        max_length=320,
        unique=True,
        blank=True,
        help_text="URL publique /concerts/<slug>/ — généré automatiquement si vide.",
    )
    type        = models.ForeignKey(EventType, on_delete=models.PROTECT)
    venue       = models.ForeignKey(Venue, on_delete=models.PROTECT)
    date_debut  = models.DateTimeField()
    date_fin    = models.DateTimeField(null=True, blank=True)
    description = models.TextField(blank=True)
    statut      = models.CharField(max_length=20, choices=Statut.choices, default=Statut.CONFIRME)
    public      = models.BooleanField(
        "Visible sur le site public",
        default=False,
        help_text=(
            "Coché = l’événement apparaît sur l’accueil et /concerts/. "
            "Activé automatiquement à la validation (hors répétitions) ; "
            "dépublication via le CMS concerts."
        ),
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sous_evenements",
        verbose_name="Événement parent",
        help_text="Festival, saison ou manifestation dans laquelle s’inscrit cet événement.",
    )
    organisme = models.CharField(
        "Organisme organisateur",
        max_length=200,
        blank=True,
        help_text="Association, mairie, festival… qui organise l’événement.",
    )
    url_billets = models.URLField(blank=True, help_text="Lien billetterie si applicable")
    contact_nom = models.CharField(
        "Contact",
        max_length=120,
        blank=True,
        help_text="Personne à contacter sur place (hors répétitions)",
    )
    contact_telephone = models.CharField("Téléphone", max_length=40, blank=True)
    contact_email = models.EmailField("E-mail", blank=True)
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events_proposed",
        verbose_name="Proposé par",
        help_text="Musicien ou adhérent ayant proposé cet événement.",
    )
    photos_request_sent_at = models.DateTimeField(
        "Demande de photos envoyée",
        null=True,
        blank=True,
        help_text="Horodatage de la notification J+7 demandant photos/vidéos aux membres.",
    )
    shares_facebook = models.PositiveIntegerField(
        "Partages Facebook",
        default=0,
        help_text="Clics sur le bouton de partage Facebook (site).",
    )
    shares_instagram = models.PositiveIntegerField(
        "Partages Instagram",
        default=0,
        help_text="Clics sur le bouton de partage Instagram (site).",
    )
    shares_bluesky = models.PositiveIntegerField(
        "Partages Bluesky",
        default=0,
        help_text="Clics sur le bouton de partage Bluesky (site).",
    )

    class Meta:
        verbose_name = "Événement"
        ordering = ["date_debut"]
        indexes = [
            models.Index(fields=["public", "date_debut"], name="event_public_date_idx"),
            models.Index(fields=["date_debut"], name="event_date_debut_idx"),
        ]

    def __str__(self):
        return f"{self.titre} ({self.date_debut:%d/%m/%Y})"

    def get_absolute_url(self):
        if not self.slug:
            return reverse("concerts")
        return reverse("concert_detail", kwargs={"slug": self.slug})

    def _build_slug_base(self) -> str:
        base = slugify(self.titre) or "concert"
        if self.date_debut:
            base = f"{base}-{self.date_debut.strftime('%Y-%m-%d')}"
        return base[:300]

    def ensure_slug(self) -> None:
        if self.slug:
            return
        base = self._build_slug_base()
        candidate = base
        n = 2
        qs = Event.objects.all()
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        while qs.filter(slug=candidate).exists():
            candidate = f"{base}-{n}"
            n += 1
        self.slug = candidate

    def save(self, *args, **kwargs):
        self.ensure_slug()
        super().save(*args, **kwargs)

    @property
    def is_rehearsal(self) -> bool:
        event_type = getattr(self, "type", None)
        if event_type is None:
            return False
        if getattr(event_type, "is_rehearsal", False):
            return True
        # Fallback legacy (types créés avant le flag explicite).
        nom = (getattr(event_type, "nom", None) or "").strip().lower()
        return "répétition" in nom or "repetition" in nom

    @property
    def has_contact(self) -> bool:
        return bool(self.contact_nom or self.contact_telephone or self.contact_email)

    @property
    def organisme_url(self) -> str:
        from events.organisme import organisme_url_for_name

        return organisme_url_for_name(self.organisme)

    @property
    def show_contact(self) -> bool:
        """Coordonnées utiles uniquement hors répétitions."""
        return self.has_contact and not self.is_rehearsal

    @property
    def lieu_affiche(self) -> str:
        """Lieu pour l’affichage public : nom, adresse exacte si connue, ville."""
        venue = self.venue
        if not venue:
            return ""
        parts = [venue.nom]
        if venue.adresse:
            parts.append(venue.adresse)
        if venue.ville:
            parts.append(venue.ville)
        return " — ".join(parts)

    @property
    def horaires_affiches(self) -> str:
        """Heure de début, et fin si renseignée (fuseau local)."""
        from django.utils import timezone as dj_tz

        debut = dj_tz.localtime(self.date_debut)
        texte = debut.strftime("%Hh%M")
        if self.date_fin:
            fin = dj_tz.localtime(self.date_fin)
            return f"{texte} – {fin.strftime('%Hh%M')}"
        return texte
