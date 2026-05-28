from django.db import models


class ExternalLink(models.Model):
    slug = models.SlugField(unique=True, help_text="ex: boutique-goodies, adhesion-helloasso")
    label = models.CharField(max_length=200)
    url = models.URLField()
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Lien externe"

    def __str__(self):
        return self.label


class MediaItem(models.Model):
    TYPE_CHOICES = [("photo", "Photo"), ("video", "Vidéo")]
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    titre = models.CharField(max_length=200, blank=True)
    fichier = models.ImageField(upload_to="medias/", null=True, blank=True)
    url_externe = models.URLField(blank=True, help_text="URL YouTube/Vimeo si vidéo")
    ordre = models.PositiveIntegerField(default=0)
    publie = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Média"
        ordering = ["ordre", "-id"]

    def __str__(self):
        return self.titre or f"Média #{self.id}"
