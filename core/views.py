from django.shortcuts import render
from django.utils import timezone
from events.models import Event
from .models import ExternalLink, MediaItem


def home(request):
    prochains = Event.objects.filter(public=True, date_debut__gte=timezone.now()).order_by("date_debut")[:3]
    return render(request, "core/home.html", {"prochains": prochains})

def concerts(request):
    prochains = Event.objects.filter(public=True, date_debut__gte=timezone.now()).order_by("date_debut")
    passes = Event.objects.filter(public=True, date_debut__lt=timezone.now()).order_by("-date_debut")[:10]
    return render(request, "core/concerts.html", {"prochains": prochains, "passes": passes})

def goodies(request):
    lien = ExternalLink.objects.filter(slug="boutique-goodies", actif=True).first()
    return render(request, "core/goodies.html", {"lien": lien})

def medias(request):
    photos = MediaItem.objects.filter(type="photo", publie=True)
    videos = MediaItem.objects.filter(type="video", publie=True)
    return render(request, "core/medias.html", {"photos": photos, "videos": videos})

def don(request):
    return render(request, "core/don.html")

def adhesion(request):
    lien = ExternalLink.objects.filter(slug="adhesion-helloasso", actif=True).first()
    return render(request, "core/adhesion.html", {"lien": lien})

def contact(request):
    return render(request, "core/contact.html")
