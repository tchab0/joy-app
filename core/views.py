from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.contenttypes.models import ContentType
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.http import JsonResponse
from django.db.models import Count, Exists, F, OuterRef
from django.urls import reverse
from datetime import timedelta
import logging
import threading

from events.models import Event, Venue, EventType
from events.forms import EventForm, VenueForm
from events.weather import attach_weather
from .cache_utils import cache_page_anonymous
from .models import ExternalLink, MediaItem, EvenementMedia, MediaVote, ContactMessage, PageBlock
from .forms import MediaSoumissionForm, ContactForm, PrestationForm
from .forms import EXTENSIONS_AUTORISEES
from .utils_compression import compresser_media
from .seo import dumps_jsonld, music_event_jsonld, music_group_jsonld, website_jsonld
from .page_cms import (
    concerts_cache_version,
    enrich_block,
    get_published_page,
    home_cache_version,
)
from users.models import User
from users.notify import notify_users

logger = logging.getLogger(__name__)


def _attach_fichier_edite(media: MediaItem, uploaded) -> None:
    """Enregistre une version retouchée et relance la compression."""
    from pathlib import Path

    dest_dir = Path(settings.MEDIA_ROOT) / "medias" / "compresses"
    # Ne pas effacer le compressé de la source (fichier) : c'est la base
    # « originale » pour une future retouche / purge. On n'enlève que l'ancien
    # sidecar de la version éditée précédente.
    if media.fichier_edite:
        old_stem = Path(media.fichier_edite.name).stem
        cand = dest_dir / f"{old_stem}.webp"
        if cand.exists():
            cand.unlink()

    if media.fichier_edite:
        media.fichier_edite.delete(save=False)
    media.fichier_edite = uploaded
    media.edite_le = timezone.now()
    media.save(update_fields=["fichier_edite", "edite_le"])
    t = threading.Thread(target=compresser_media, args=(media,), daemon=True)
    t.start()


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


NAV_GO_DAYS_BEFORE = 3


def _attach_nav_go(events):
    """Marque show_nav_go si GPS + concert dans les 3 jours (hors annulé)."""
    now = timezone.now()
    window_end = now + timedelta(days=NAV_GO_DAYS_BEFORE)
    for e in events:
        has_gps = bool(
            e.venue and e.venue.latitude is not None and e.venue.longitude is not None
        )
        e.show_nav_go = bool(
            has_gps
            and e.statut != Event.Statut.ANNULE
            and e.date_debut <= window_end
        )
    return events


@cache_page_anonymous(settings.CACHE_TTL_HOME, key_prefix=lambda: f"home-v{home_cache_version()}")
def home(request):
    page = get_published_page("accueil")
    blocks = []
    concerts_limit = 3
    if page:
        for block in page.blocks.all():
            enrich_block(block)
            blocks.append(block)
            if block.type == PageBlock.TYPE_CONCERTS:
                concerts_limit = max(concerts_limit, int(block.render.get("limit") or 3))

    qs = _public_events_qs().filter(date_debut__gte=timezone.now()).order_by("date_debut")[
        :concerts_limit
    ]
    prochains_all = []
    for e in qs:
        e.bbox = None
        if e.venue and e.venue.latitude and e.venue.longitude:
            lat = float(e.venue.latitude)
            lng = float(e.venue.longitude)
            e.bbox = f"{lng-0.003},{lat-0.003},{lng+0.003},{lat+0.003}"
        prochains_all.append(e)
    _attach_nav_go(prochains_all)

    has_concerts_block = False
    for block in blocks:
        if block.type == PageBlock.TYPE_CONCERTS:
            has_concerts_block = True
            lim = int(block.render.get("limit") or 3)
            block.prochains = prochains_all[:lim]

    ctx = {
        "page": page,
        "blocks": blocks,
        "prochains": prochains_all[:3],
        "has_concerts_block": has_concerts_block,
        "json_ld": dumps_jsonld(music_group_jsonld(), website_jsonld()),
        "use_cms": bool(page and blocks),
    }
    return render(request, "core/home.html", ctx)


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


@cache_page_anonymous(
    settings.CACHE_TTL_CONCERTS,
    key_prefix=lambda: f"concerts-v{concerts_cache_version()}",
)
def concerts(request):
    prochains = _attach_nav_go(
        _add_bbox(
            _public_events_qs().filter(date_debut__gte=timezone.now()).order_by("date_debut")
        )
    )
    attach_weather(prochains)
    passes = _public_events_qs().filter(date_debut__lt=timezone.now()).order_by("-date_debut")[:10]
    events_ld = [music_event_jsonld(e) for e in prochains]
    return render(
        request,
        "core/concerts.html",
        {
            "prochains": prochains,
            "passes": passes,
            "json_ld": dumps_jsonld(music_group_jsonld(), *events_ld)
            if events_ld
            else dumps_jsonld(music_group_jsonld()),
        },
    )


@cache_page_anonymous(
    settings.CACHE_TTL_CONCERTS,
    key_prefix=lambda: f"concerts-v{concerts_cache_version()}",
)
def concert_detail(request, slug):
    event = get_object_or_404(
        _public_events_qs(),
        slug=slug,
        public=True,
    )
    events = _attach_nav_go(_add_bbox([event]))
    event = events[0]
    attach_weather([event])
    desc = event.description.strip() if event.description else (
        f"Concert de Jazz Orchestra Yonnais (JOY) — {event.titre} "
        f"le {event.date_debut:%d/%m/%Y} à {event.lieu_affiche}."
    )
    return render(
        request,
        "core/concert_detail.html",
        {
            "event": event,
            "meta_description": desc[:160],
            "json_ld": dumps_jsonld(music_group_jsonld(), music_event_jsonld(event)),
        },
    )


@cache_page_anonymous(settings.CACHE_TTL_GOODIES)
def goodies(request):
    lien = ExternalLink.objects.filter(slug="boutique-goodies", actif=True).first()
    return render(request, "core/goodies.html", {"lien": lien})


@cache_page_anonymous(settings.CACHE_TTL_ADHESION)
def mentions_legales(request):
    return render(
        request,
        "core/mentions_legales.html",
        {"admin_email": settings.ADMIN_EMAIL},
    )


def medias(request):
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key

    tri = (request.GET.get("tri") or "evenements").strip().lower()
    if tri not in ("evenements", "votes"):
        tri = "evenements"

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

    photos_qs = annoter(
        MediaItem.objects.filter(
            type="photo", publie=True, evenement__isnull=False
        ).select_related("evenement")
    )

    groupes_photos = []
    photos_votes = []

    if tri == "votes":
        photos_votes = list(
            photos_qs.order_by("-nb_votes", "-evenement__date", "evenement_id", "id")
        )
        for p in photos_votes:
            p.display_url = p.url_affichage
    else:
        # Chronologie inverse : événements les plus récents d'abord.
        photos = list(
            photos_qs.order_by(
                F("evenement__date").desc(nulls_last=True),
                "evenement_id",
                "ordre",
                "id",
            )
        )
        groupes_map: dict = {}
        for p in photos:
            # Compute display URL once (avoids repeated Path.exists() in template).
            p.display_url = p.url_affichage
            key = p.evenement_id
            if key not in groupes_map:
                groupe = {"evenement": p.evenement, "photos": []}
                groupes_map[key] = groupe
                groupes_photos.append(groupe)
            groupes_map[key]["photos"].append(p)

    return render(request, "core/medias.html", {
        "groupes_photos": groupes_photos,
        "photos_votes": photos_votes,
        "tri": tri,
        "videos": videos,
        "audios": audios,
        "pdfs": pdfs,
    })


def proposer_media(request):
    from events.models import Event

    from core.media_events import ensure_evenement_media_for_event

    planning_event = None
    prefilled_media_event = None
    event_pk_raw = (request.GET.get("event") or request.POST.get("event") or "").strip()
    if event_pk_raw.isdigit():
        planning_event = (
            Event.objects.filter(pk=int(event_pk_raw))
            .exclude(statut=Event.Statut.ANNULE)
            .select_related("venue")
            .first()
        )
        if planning_event is not None:
            prefilled_media_event = ensure_evenement_media_for_event(planning_event)

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
                    return render(
                        request,
                        "core/proposer_media.html",
                        _proposer_media_context(
                            form, planning_event, prefilled_media_event
                        ),
                    )

                medias_crees = []
                for i, f in enumerate(fichiers):
                    if f.size > 1 * 1024 * 1024 * 1024:
                        continue
                    ext = "." + f.name.rsplit(".", 1)[-1].lower() if "." in (f.name or "") else ""
                    if ext not in EXTENSIONS_AUTORISEES["photo"]:
                        form.add_error(
                            "fichiers_multiples",
                            f"Extension non autorisée pour « {f.name} ». "
                            f"Acceptées : {', '.join(EXTENSIONS_AUTORISEES['photo'])}",
                        )
                        return render(
                            request,
                            "core/proposer_media.html",
                            _proposer_media_context(
                                form, planning_event, prefilled_media_event
                            ),
                        )
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
                    edite = request.FILES.get(f"fichier_edite_{i}")
                    if edite and edite.size and edite.size <= 1 * 1024 * 1024 * 1024:
                        _attach_fichier_edite(media, edite)
                    else:
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
        initial = {"type": "photo"}
        if request.user.is_authenticated:
            full = (request.user.get_full_name() or "").strip()
            if full:
                initial["soumis_par_nom"] = full
            if request.user.email:
                initial["soumis_par_email"] = request.user.email
        if prefilled_media_event is not None:
            initial["evenement_existant"] = prefilled_media_event.pk
        form = MediaSoumissionForm(initial=initial)

    return render(
        request,
        "core/proposer_media.html",
        _proposer_media_context(form, planning_event, prefilled_media_event),
    )


def _proposer_media_context(form, planning_event, prefilled_media_event):
    return {
        "form": form,
        "planning_event": planning_event,
        "prefilled_media_event": prefilled_media_event,
    }


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


def _contact_mode(request) -> str:
    mode = (request.POST.get("mode") or request.GET.get("mode") or "contact").strip()
    if mode not in ("contact", "prestation"):
        return "contact"
    return mode


def _notify_staff_contact(msg: ContactMessage) -> None:
    staff = User.objects.filter(
        is_active=True,
        is_staff=True,
        notify_contact_messages=True,
    )
    if msg.is_prestation:
        title = "JOY — Demande de prestation"
        bits = [
            f"{msg.nom}",
            msg.type_evenement and msg.get_type_evenement_display(),
            msg.ville,
            msg.date_souhaitee and msg.date_souhaitee.strftime("%d/%m/%Y"),
        ]
        body = " · ".join(b for b in bits if b)
    else:
        title = "JOY — Message de contact"
        body = f"{msg.nom} : {(msg.message or '')[:120]}"
    try:
        notify_users(staff, title=title, body=body or title, url="/admin-contact/")
    except Exception:
        logger.exception("Échec notification staff contact id=%s", msg.pk)


def contact(request):
    success = False
    mode = _contact_mode(request)
    contact_form = ContactForm()
    prestation_form = PrestationForm()

    if request.method == "POST":
        if mode == "prestation":
            prestation_form = PrestationForm(request.POST)
            if prestation_form.is_valid():
                data = prestation_form.cleaned_data
                msg = ContactMessage.objects.create(
                    kind=ContactMessage.KIND_PRESTATION,
                    nom=data["nom"],
                    organisation=data.get("organisation") or "",
                    telephone=data["telephone"],
                    email=data["email"],
                    profil=data["profil"],
                    message=data.get("message") or "",
                    type_evenement=data["type_evenement"],
                    date_souhaitee=data["date_souhaitee"],
                    date_flexible=data.get("date_flexible") or False,
                    date_alternative=data.get("date_alternative"),
                    ville=data["ville"],
                    lieu_nom=data.get("lieu_nom") or "",
                    lieu_adresse=data.get("lieu_adresse") or "",
                    lieu_type=data["lieu_type"],
                    heure_debut=data["heure_debut"],
                    heure_fin=data.get("heure_fin"),
                    duree_jeu=data["duree_jeu"],
                    jauge=data["jauge"],
                    role_ambiance=data["role_ambiance"],
                    sono=data["sono"],
                    scene_details=data.get("scene_details") or "",
                    acces_logistique=data.get("acces_logistique") or "",
                    budget=data["budget"],
                    source=data.get("source") or "",
                )
                _notify_staff_contact(msg)
                prestation_form = PrestationForm()
                success = True
        else:
            contact_form = ContactForm(request.POST)
            if contact_form.is_valid():
                data = contact_form.cleaned_data
                msg = ContactMessage.objects.create(
                    kind=ContactMessage.KIND_CONTACT,
                    nom=data["nom"],
                    telephone=data["telephone"],
                    email=data["email"],
                    message=data["message"],
                )
                _notify_staff_contact(msg)
                contact_form = ContactForm()
                success = True

    return render(request, "core/contact.html", {
        "mode": mode,
        "contact_form": contact_form,
        "prestation_form": prestation_form,
        "success": success,
        "send_error": False,
    })


@staff_member_required
def admin_contact(request):
    statut = request.GET.get("statut", "")
    kind = request.GET.get("kind", "")
    messages_qs = ContactMessage.objects.all()
    if statut:
        messages_qs = messages_qs.filter(statut=statut)
    if kind in (ContactMessage.KIND_CONTACT, ContactMessage.KIND_PRESTATION):
        messages_qs = messages_qs.filter(kind=kind)
    messages_qs = messages_qs.order_by("-created_at")

    return render(request, "core/admin_contact.html", {
        "messages_list": messages_qs,
        "statut_actif": statut,
        "kind_actif": kind,
        "statut_choices": ContactMessage.STATUS_CHOICES,
        "kind_choices": ContactMessage.KIND_CHOICES,
    })


@staff_member_required
def admin_contact_delete(request, pk):
    if request.method == "POST":
        ContactMessage.objects.filter(pk=pk).delete()
    return redirect("admin_contact")


@staff_member_required
def admin_notifications(request):
    """Notifications aux musiciens : non lues et/ou non répondues."""
    from django.db.models import Q

    from users.models import UserNotification

    filtre = request.GET.get("filtre", "en-attente")
    base = UserNotification.objects.filter(user__is_musician=True).select_related(
        "user"
    )
    unread_q = Q(read_at__isnull=True)
    unanswered_q = Q(requires_response=True, responded_at__isnull=True)

    if filtre == "non-lues":
        qs = base.filter(unread_q)
    elif filtre == "non-repondues":
        qs = base.filter(unanswered_q)
    elif filtre == "toutes":
        qs = base
    else:
        filtre = "en-attente"
        qs = base.filter(unread_q | unanswered_q)

    qs = qs.order_by("-created_at")
    return render(
        request,
        "core/admin_notifications.html",
        {
            "notifications": qs[:200],
            "total": qs.count(),
            "filtre_actif": filtre,
            "count_unread": base.filter(unread_q).count(),
            "count_unanswered": base.filter(unanswered_q).count(),
            "count_pending": base.filter(unread_q | unanswered_q).count(),
        },
    )


@staff_member_required
def admin_notification_delete(request, pk):
    from users.models import UserNotification

    if request.method == "POST":
        UserNotification.objects.filter(pk=pk).delete()
        messages.success(request, "Notification supprimée.")
    next_filtre = request.POST.get("filtre") or request.GET.get("filtre") or ""
    if next_filtre:
        return redirect(f"{reverse('admin_notifications')}?filtre={next_filtre}")
    return redirect("admin_notifications")


def media_vote(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "POST requis"}, status=405)
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key
    media = MediaItem.objects.filter(pk=pk, publie=True).first()
    if not media:
        return JsonResponse({"error": "introuvable"}, status=404)
    from django.db import IntegrityError

    try:
        vote, created = MediaVote.objects.get_or_create(
            media=media, session_key=session_key
        )
    except IntegrityError:
        vote = MediaVote.objects.filter(media=media, session_key=session_key).first()
        created = False
    if not created and vote is not None:
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
    media = get_object_or_404(MediaItem, pk=pk)
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


@staff_member_required
def admin_media_edit(request, pk):
    """Enregistre une version retouchée (JPEG HD) pour une photo."""
    if request.method != "POST":
        return JsonResponse({"error": "POST requis"}, status=405)
    media = get_object_or_404(MediaItem, pk=pk)
    if media.type != "photo":
        return JsonResponse({"error": "Réservé aux photos"}, status=400)
    uploaded = request.FILES.get("fichier_edite")
    if not uploaded:
        return JsonResponse({"error": "Fichier manquant"}, status=400)
    if uploaded.size > 25 * 1024 * 1024:
        return JsonResponse({"error": "Fichier trop volumineux"}, status=400)
    _attach_fichier_edite(media, uploaded)
    return JsonResponse({
        "ok": True,
        "url_edite": media.fichier_edite.url if media.fichier_edite else "",
        "url_affichage": media.url_affichage,
    })


@cache_page_anonymous(settings.CACHE_TTL_DON)
def don(request):
    return render(request, "core/don.html")


@cache_page_anonymous(settings.CACHE_TTL_ADHESION)
def adhesion(request):
    lien = ExternalLink.objects.filter(slug="adhesion-helloasso", actif=True).first()
    return render(request, "core/adhesion.html", {"lien": lien})


@staff_member_required
def admin_hub(request):
    """Point d’entrée unique pour les outils staff (CMS + ops orchestre)."""
    return render(request, "core/admin_hub.html")


@staff_member_required
def admin_concerts(request):
    events = Event.objects.select_related("venue", "type").order_by("date_debut")
    return render(request, "core/admin_concerts.html", {"events": events})


@staff_member_required
def admin_concert_edit(request, pk=None):
    instance = get_object_or_404(Event, pk=pk) if pk else None
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
    instance = get_object_or_404(Venue, pk=pk) if pk else None
    if request.method == "POST":
        form = VenueForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            return redirect("admin_venues")
    else:
        form = VenueForm(instance=instance)
    return render(request, "core/admin_venue_edit.html", {"form": form, "instance": instance})
