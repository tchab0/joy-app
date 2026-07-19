from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.contenttypes.models import ContentType
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.cache import cache_page
from django.db.models import Count, Exists, OuterRef
import logging
import threading

from events.models import Event, Venue, EventType
from events.forms import EventForm, VenueForm
from .models import ExternalLink, MediaItem, EvenementMedia, MediaVote, ContactMessage
from .forms import MediaSoumissionForm, ContactForm
from .utils_compression import compresser_media

logger = logging.getLogger(__name__)

PAGE_LABELS = {
    (7,  "core",   "externallink"): "Liens externes",
    (8,  "core",   "mediaitem"):    "Médias",
    (9,  "events", "event"):        "Concerts",
    (10, "events", "eventtype"):    "Types d'événement",
    (11, "events", "venue"):        "Salles / Lieux",
}


def _public_events_qs():
    return Event.objects.filter(public=True).select_related(
        "venue", "type", "parent", "parent__venue"
    )


@cache_page(settings.CACHE_TTL_HOME)
def home(request):
    qs = _public_events_qs().filter(date_debut__gte=timezone.now()).order_by("date_debut")[:3]
    prochains = []
    for e in qs:
        e.bbox = None
        if e.venue and e.venue.latitude and e.venue.longitude:
            lat = float(e.venue.latitude)
            lng = float(e.venue.longitude)
            e.bbox = f"{lng-0.003},{lat-0.003},{lng+0.003},{lat+0.003}"
        prochains.append(e)
    return render(request, "core/home.html", {"prochains": prochains})


def _add_bbox(qs):
    result = []
    for e in qs:
        e.bbox = None
        if e.venue and e.venue.latitude and e.venue.longitude:
            lat = float(e.venue.latitude)
            lng = float(e.venue.longitude)
            e.bbox = f"{lng-0.003},{lat-0.003},{lng+0.003},{lat+0.003}"
        result.append(e)
    return result


@cache_page(settings.CACHE_TTL_CONCERTS)
def concerts(request):
    prochains = _add_bbox(
        _public_events_qs().filter(date_debut__gte=timezone.now()).order_by("date_debut")
    )
    passes = _public_events_qs().filter(date_debut__lt=timezone.now()).order_by("-date_debut")[:10]
    return render(request, "core/concerts.html", {"prochains": prochains, "passes": passes})


@cache_page(settings.CACHE_TTL_GOODIES)
def goodies(request):
    lien = ExternalLink.objects.filter(slug="boutique-goodies", actif=True).first()
    return render(request, "core/goodies.html", {"lien": lien})


def medias(request):
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key

    def annoter(qs):
        return qs.annotate(
            nb_votes=Count("votes"),
            user_a_vote=Exists(
                MediaVote.objects.filter(media=OuterRef("pk"), session_key=session_key)
            )
        )

    videos = annoter(MediaItem.objects.filter(type="video", publie=True))
    audios = annoter(MediaItem.objects.filter(type="audio", publie=True))
    pdfs = annoter(MediaItem.objects.filter(type="pdf", publie=True))

    evenements = EvenementMedia.objects.filter(items__type="photo").distinct().order_by("-date", "nom")

    groupes_photos = []
    for ev in evenements:
        photos = list(
            annoter(MediaItem.objects.filter(evenement=ev, type="photo", publie=True)).order_by("ordre", "id")
        )
        if photos:
            groupes_photos.append({"evenement": ev, "photos": photos})

    return render(request, "core/medias.html", {
        "groupes_photos": groupes_photos,
        "videos": videos,
        "audios": audios,
        "pdfs": pdfs,
    })


def proposer_media(request):
    if request.method == "POST":
        form = MediaSoumissionForm(request.POST, request.FILES)
        if form.is_valid():
            type_media = form.cleaned_data["type"]
            nom = form.cleaned_data["soumis_par_nom"]
            email = form.cleaned_data["soumis_par_email"]
            evenement = form.get_or_create_evenement()

            if type_media == "photo":
                fichiers = request.FILES.getlist("fichiers_multiples")
                if not fichiers:
                    f = form.cleaned_data.get("fichier")
                    fichiers = [f] if f else []
                if not fichiers:
                    form.add_error("fichiers_multiples", "Sélectionnez au moins une photo.")
                    return render(request, "core/proposer_media.html", {"form": form})

                medias_crees = []
                for f in fichiers:
                    if f.size > 1 * 1024 * 1024 * 1024:
                        continue
                    media = MediaItem(
                        type="photo",
                        titre=evenement.nom,
                        evenement=evenement,
                        fichier=f,
                        soumis_par_nom=nom,
                        soumis_par_email=email,
                        publie=False,
                        statut="en_attente",
                    )
                    media.save()
                    t = threading.Thread(target=compresser_media, args=(media,), daemon=True)
                    t.start()
                    medias_crees.append(media)

                if medias_crees:
                    _notifier_admin(medias_crees[0], len(medias_crees))
                return render(request, "core/proposer_media_succes.html", {
                    "evenement": evenement,
                    "nb": len(medias_crees),
                })
            else:
                media = form.save(commit=False)
                media.evenement = evenement
                media.titre = evenement.nom
                media.publie = False
                media.statut = "en_attente"
                media.save()
                if media.fichier:
                    t = threading.Thread(target=compresser_media, args=(media,), daemon=True)
                    t.start()
                _notifier_admin(media)
                return render(request, "core/proposer_media_succes.html", {
                    "evenement": evenement, "nb": 1
                })
    else:
        form = MediaSoumissionForm()
    return render(request, "core/proposer_media.html", {"form": form})


def _notifier_admin(media, nb=1):
    try:
        sujet = f"[JOY] {nb} média(s) soumis — {media.evenement or media.titre or '?'}"
        corps = (
            f"{nb} média(s) soumis.\n\n"
            f"Type       : {media.get_type_display()}\n"
            f"Événement  : {media.evenement or '(sans événement)'}\n"
            f"Par        : {media.soumis_par_nom or 'Anonyme'} <{media.soumis_par_email}>\n"
            f"Le         : {media.soumis_le.strftime('%d/%m/%Y %H:%M')}\n\n"
            f"Validation : {settings.SITE_URL}/admin-medias/"
        )
        send_mail(sujet, corps, settings.DEFAULT_FROM_EMAIL, [settings.ADMIN_EMAIL], fail_silently=True)
    except Exception:
        logger.exception("Erreur notification admin media")


def contact(request):
    success = False

    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            ContactMessage.objects.create(
                nom=form.cleaned_data["nom"],
                telephone=form.cleaned_data["telephone"],
                email=form.cleaned_data["email"],
                message=form.cleaned_data["message"],
            )
            form = ContactForm()
            success = True
    else:
        form = ContactForm()

    return render(request, "core/contact.html", {
        "form": form,
        "success": success,
        "send_error": False,
    })


@staff_member_required
def admin_contact(request):
    statut = request.GET.get("statut", "")
    messages_qs = ContactMessage.objects.all()
    if statut:
        messages_qs = messages_qs.filter(statut=statut)
    messages_qs = messages_qs.order_by("-created_at")

    return render(request, "core/admin_contact.html", {
        "messages_list": messages_qs,
        "statut_actif": statut,
        "statut_choices": ContactMessage.STATUS_CHOICES,
    })


def media_vote(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "POST requis"}, status=405)
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key
    media = MediaItem.objects.filter(pk=pk, publie=True).first()
    if not media:
        return JsonResponse({"error": "introuvable"}, status=404)
    vote, created = MediaVote.objects.get_or_create(media=media, session_key=session_key)
    if not created:
        vote.delete()
        voted = False
    else:
        voted = True
    nb = media.votes.count()
    return JsonResponse({"voted": voted, "nb": nb})


@staff_member_required
def admin_medias(request):
    statut = request.GET.get("statut", "en_attente")
    medias_qs = MediaItem.objects.filter(statut=statut).annotate(nb_votes=Count("votes")).order_by("-soumis_le")

    pages_disponibles = []
    for ct in ContentType.objects.filter(app_label__in=["core", "events", "planning"]).order_by("app_label", "model"):
        label = PAGE_LABELS.get((ct.pk, ct.app_label, ct.model), f"{ct.app_label} › {ct.model}")
        try:
            for obj in ct.model_class().objects.all()[:50]:
                pages_disponibles.append({"ct_id": ct.pk, "obj_id": obj.pk, "label": label, "nom": str(obj)})
        except Exception:
            pass

    return render(request, "core/admin_medias.html", {
        "medias": medias_qs,
        "statut_actif": statut,
        "statut_choices": MediaItem.STATUT_CHOICES,
        "pages_disponibles": pages_disponibles,
    })


@staff_member_required
def admin_media_action(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "POST requis"}, status=405)
    media = MediaItem.objects.get(pk=pk)
    action = request.POST.get("action")
    if action == "publier":
        media.publie = True
        media.statut = "publie"
        media.save(update_fields=["publie", "statut"])
    elif action == "refuser":
        media.publie = False
        media.statut = "refuse"
        media.note_admin = request.POST.get("note", "")
        media.save(update_fields=["publie", "statut", "note_admin"])
    elif action == "rattacher":
        ct_id = request.POST.get("content_type_id")
        obj_id = request.POST.get("object_id")
        if ct_id and obj_id:
            media.content_type_id = ct_id
            media.object_id = obj_id
            media.save(update_fields=["content_type_id", "object_id"])
    return JsonResponse({"ok": True, "statut": media.statut})


@cache_page(settings.CACHE_TTL_DON)
def don(request):
    return render(request, "core/don.html")


@cache_page(settings.CACHE_TTL_ADHESION)
def adhesion(request):
    lien = ExternalLink.objects.filter(slug="adhesion-helloasso", actif=True).first()
    return render(request, "core/adhesion.html", {"lien": lien})


@staff_member_required
def admin_concerts(request):
    events = Event.objects.select_related("venue", "type").order_by("date_debut")
    return render(request, "core/admin_concerts.html", {"events": events})


@staff_member_required
def admin_concert_edit(request, pk=None):
    instance = Event.objects.get(pk=pk) if pk else None
    if request.method == "POST":
        form = EventForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            return redirect("admin_concerts")
    else:
        form = EventForm(instance=instance)
    return render(request, "core/admin_concert_edit.html", {"form": form, "instance": instance})


@staff_member_required
def admin_concert_delete(request, pk):
    if request.method == "POST":
        Event.objects.filter(pk=pk).delete()
    return redirect("admin_concerts")


@staff_member_required
def admin_venues(request):
    venues = Venue.objects.all().order_by("ville", "nom")
    return render(request, "core/admin_venues.html", {"venues": venues})


@staff_member_required
def admin_venue_edit(request, pk=None):
    instance = Venue.objects.get(pk=pk) if pk else None
    if request.method == "POST":
        form = VenueForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            return redirect("admin_venues")
    else:
        form = VenueForm(instance=instance)
    return render(request, "core/admin_venue_edit.html", {"form": form, "instance": instance})
