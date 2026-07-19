from django.db import models


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


class EventType(models.Model):
    nom = models.CharField(max_length=100)

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
    type        = models.ForeignKey(EventType, on_delete=models.PROTECT)
    venue       = models.ForeignKey(Venue, on_delete=models.PROTECT)
    date_debut  = models.DateTimeField()
    date_fin    = models.DateTimeField(null=True, blank=True)
    description = models.TextField(blank=True)
    statut      = models.CharField(max_length=20, choices=Statut.choices, default=Statut.CONFIRME)
    public      = models.BooleanField(
        "Visible sur le site public",
        default=False,
        help_text="Coché = l’événement apparaît sur l’accueil et /concerts/.",
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

    class Meta:
        verbose_name = "Événement"
        ordering = ["date_debut"]

    def __str__(self):
        return f"{self.titre} ({self.date_debut:%d/%m/%Y})"

    @property
    def is_rehearsal(self) -> bool:
        nom = (getattr(self.type, "nom", None) or "").strip().lower()
        return "répétition" in nom or "repetition" in nom

    @property
    def has_contact(self) -> bool:
        return bool(self.contact_nom or self.contact_telephone or self.contact_email)

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
