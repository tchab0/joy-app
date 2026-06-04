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
    public      = models.BooleanField(default=True)
    url_billets = models.URLField(blank=True, help_text="Lien billetterie si applicable")

    class Meta:
        verbose_name = "Événement"
        ordering = ["date_debut"]

    def __str__(self):
        return f"{self.titre} ({self.date_debut:%d/%m/%Y})"
