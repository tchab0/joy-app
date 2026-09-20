"""Rappel matinal joyeux aux musiciens présents le jour d’un événement."""

from __future__ import annotations

import logging
from django.contrib.auth import get_user_model
from django.db import OperationalError, ProgrammingError
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from events.weather import forecast_for_event, format_weather_line
from planning.models import EventParticipation, EventRoadmap
from planning.services._notify import notify_users

logger = logging.getLogger(__name__)

User = get_user_model()


def venue_address_line(event: Event) -> str:
    """Adresse lisible (nom + rue + ville, sans doublon)."""
    venue = getattr(event, "venue", None)
    if venue is None:
        return ""
    nom = (venue.nom or "").strip()
    adresse = (venue.adresse or "").strip()
    ville = (venue.ville or "").strip()
    parts: list[str] = []
    if nom:
        parts.append(nom)
    if adresse:
        parts.append(adresse)
        # Adresse postale complète → ne pas répéter la ville.
        ville_key = "".join(ch for ch in ville.casefold() if ch.isalnum())
        addr_key = "".join(ch for ch in adresse.casefold() if ch.isalnum())
        if ville_key and ville_key not in addr_key:
            parts.append(ville)
    elif ville:
        parts.append(ville)
    return " — ".join(parts)


def present_musicians_for_event(event: Event):
    """Musiciens positionnés présents (confirmés, avec poste)."""
    return (
        EventParticipation.objects.filter(
            event=event,
            status__code="confirmed",
        )
        .exclude(Q(poste="") | Q(poste__isnull=True))
        .select_related("user")
        .order_by("user__last_name", "user__first_name", "user_id")
    )


def active_setlist_for_event(event: Event):
    """Setlist active liée à l’événement, si présente."""
    try:
        from repertoire.models import Setlist

        return (
            Setlist.objects.filter(event=event, is_active=True)
            .order_by("-updated_at", "-pk")
            .first()
        )
    except (ProgrammingError, OperationalError):
        logger.warning(
            "active_setlist_for_event: schéma manquant event_id=%s", event.pk
        )
        return None


def _fmt_clock(value) -> str:
    """15:30 → 15h30 ; 15:00 → 15h."""
    return value.strftime("%Hh%M").replace("h00", "h")


def arrival_rendezvous_phrase(roadmap: EventRoadmap | None, event: Event) -> str:
    """
    Libellé du rendez-vous = créneau d’arrivée (feuille de route),
    sinon repli sur l’heure de début du concert.
    """
    if roadmap is not None:
        start = roadmap.arrival_start
        end = roadmap.arrival_end
        if start and end:
            return f"entre {_fmt_clock(start)} et {_fmt_clock(end)}"
        if start:
            return f"dès {_fmt_clock(start)}"
        if end:
            return f"avant {_fmt_clock(end)}"
    local = timezone.localtime(event.date_debut)
    return f"vers {_fmt_clock(local)}"


_WEATHER_EMOJI = {
    "sun": "☀️",
    "cloud-sun": "🌤️",
    "cloud": "☁️",
    "fog": "🌫️",
    "snow": "❄️",
    "storm": "⛈️",
    "rain": "🌧️",
}


def weather_emoji(weather: dict | None) -> str:
    """Emoji météo à partir du champ ``icon`` Open-Meteo."""
    if not weather:
        return "🌤️"
    return _WEATHER_EMOJI.get(str(weather.get("icon") or ""), "🌤️")


def build_morning_reminder_message(event: Event) -> tuple[str, str, str]:
    """
    Retourne (title, body, url_path) pour le rappel du jour J.

    Inclut adresse, météo (si dispo), feuille de route et setlist.
    L’heure de rendez-vous est l’arrivée (feuille de route), pas le concert.
    Corps en markdown léger (gras / italique / titres / listes) pour salon & inbox.
    """
    from django.conf import settings

    try:
        roadmap = EventRoadmap.objects.filter(event=event).first()
    except (ProgrammingError, OperationalError):
        roadmap = None

    rv = arrival_rendezvous_phrase(roadmap, event)
    address = venue_address_line(event)
    weather = forecast_for_event(event)
    weather_line = format_weather_line(weather)
    site = getattr(settings, "SITE_URL", "https://jazz-orchestra-yonnais.fr").rstrip(
        "/"
    )
    roadmap_path = reverse("planning:event_roadmap", kwargs={"pk": event.pk})
    setlist_path = (
        reverse("planning:event_detail", kwargs={"pk": event.pk}) + "#setlist"
    )
    setlist = active_setlist_for_event(event)

    title = f"🎺 JOY — C’est le grand jour · {event.titre}"
    lines = [
        f"Bonjour ! Aujourd’hui, c’est **« {event.titre} »** — "
        f"rendez-vous ++{rv}++.",
        "",
    ]
    if address:
        lines.append(f"📍 **Lieu** : {address}")
        lines.append("")
    if weather_line:
        lines.append(f"{weather_emoji(weather)} **Météo** : {weather_line}")
        lines.append("")
    lines.append("### ✅ Tout est prêt pour ce soir")
    lines.append(f"- [Feuille de route]({site}{roadmap_path})")
    if setlist is not None:
        lines.append(f"- [Setlist « {setlist.title} »]({site}{setlist_path})")
    else:
        lines.append(f"- [Setlist]({site}{setlist_path})")
    lines.append("")
    lines.append("_Bonne journée, et à tout à l’heure sur scène !_")
    body = "\n".join(lines).strip()
    return title, body, roadmap_path


def events_due_for_morning_reminder(*, today=None):
    """Événements confirmés (hors répétition) dont le jour local est ``today``."""
    if today is None:
        today = timezone.localdate()
    qs = (
        Event.objects.filter(statut=Event.Statut.CONFIRME)
        .exclude(type__is_rehearsal=True)
        .exclude(statut=Event.Statut.ANNULE)
        .filter(morning_reminder_sent_at__isnull=True)
        .select_related("type", "venue")
        .order_by("date_debut")
    )
    due = []
    for event in qs:
        if timezone.localtime(event.date_debut).date() == today:
            due.append(event)
    return due


def send_event_morning_reminders(
    events,
    *,
    only_user=None,
    mark_sent: bool = True,
    force_immediate: bool = True,
) -> int:
    """
    Envoie le rappel matinal aux présents de chaque événement.

    ``only_user`` : restreindre à un destinataire (essais).
    ``mark_sent`` : horodater ``morning_reminder_sent_at`` (désactiver en essai).
    Retourne le nombre de notifications livrées (push/e-mail).
    """
    events = list(events)
    if not events:
        return 0

    total = 0
    now = timezone.now()
    for event in events:
        try:
            roadmap = EventRoadmap.objects.filter(event=event).first()
        except (ProgrammingError, OperationalError):
            logger.warning(
                "send_event_morning_reminders: schéma roadmap manquant event_id=%s",
                event.pk,
            )
            roadmap = None
        if roadmap is None:
            logger.info(
                "Rappel matin sauté (pas de feuille de route) event_id=%s",
                event.pk,
            )
            if mark_sent:
                Event.objects.filter(pk=event.pk).update(morning_reminder_sent_at=now)
                event.morning_reminder_sent_at = now
            continue

        title, body, url = build_morning_reminder_message(event)
        parts = list(present_musicians_for_event(event))
        users = [p.user for p in parts]
        if only_user is not None:
            uid = getattr(only_user, "pk", only_user)
            users = [u for u in users if u.pk == uid]
            if not users and getattr(only_user, "pk", None):
                # Essai staff même sans participation confirmée.
                users = [only_user]

        if users:
            total += notify_users(
                users,
                title=title,
                body=body,
                url=url,
                related_type="event",
                related_id=event.pk,
                notify_type="event",
                force_immediate=force_immediate,
            )

        # Miroir dans le salon concert (sauf essai --only-user).
        if only_user is None:
            try:
                from chat.services import post_event_notification_to_room

                post_event_notification_to_room(event, title=title, body=body)
            except Exception:
                logger.exception(
                    "Miroir salon rappel matin échoué event_id=%s", event.pk
                )

        if mark_sent:
            Event.objects.filter(pk=event.pk).update(morning_reminder_sent_at=now)
            event.morning_reminder_sent_at = now

    return total


def resolve_only_user(spec: str):
    """Résout un user par pk numérique, username ou e-mail."""
    spec = (spec or "").strip()
    if not spec:
        return None
    if spec.isdigit():
        return User.objects.filter(pk=int(spec)).first()
    return (
        User.objects.filter(username__iexact=spec).first()
        or User.objects.filter(email__iexact=spec).first()
    )
