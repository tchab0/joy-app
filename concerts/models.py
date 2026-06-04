from django.db import models

class Lieu(models.Model):
    nom = models.CharField(max_length=200)
    ville = models.CharField(max_length=100)
    adresse = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name_plural = "Lieux"
        ordering = ['ville']

    def __str__(self):
        return f"{self.nom} – {self.ville}"


class Concert(models.Model):
    class Statut(models.TextChoices):
        CONFIRME  = 'confirme',  'Confirmé'
        TENTATIVE = 'tentative', 'Tentative'
        ANNULE    = 'annule',    'Annulé'

    titre       = models.CharField(max_length=200)
    date        = models.DateField()
    heure       = models.TimeField(null=True, blank=True)
    lieu        = models.ForeignKey(Lieu, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField(blank=True)
    statut      = models.CharField(max_length=20, choices=Statut.choices, default=Statut.CONFIRME)
    public      = models.BooleanField(default=True, help_text="Visible sur le site public")
    url_billets = models.URLField(blank=True, help_text="Lien billetterie si applicable")

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f"{self.date} – {self.titre}"
