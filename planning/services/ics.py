"""Export iCalendar (.ics) — événement unitaire et flux d’abonnement musiciens."""
from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import quote

from django.conf import settings
from django.db.models import Q, QuerySet
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from events.models import Event
from planning.models import EventParticipation, EventRoadmap

# Durée par défaut si date_fin absente (concert / répé).
_DEFAULT_DURATION = timedelta(hours=2)
# Passé récent inclus dans les flux d’abonnement.
_FEED_LOOKBACK = timedelta(days=30)

# Participations visibles dans « Mes dates » (hors déclin / remplacement).
MINE_PARTICIPATION_CODES = frozenset({"confirmed", "maybe", "invited"})


def new_calendar_feed_token() -> str:
    return secrets.token_urlsafe(32)


def ensure_calendar_feed_token(user) -> str:
    """Retourne le jeton existant ou en crée un (persisté)."""
    token = (getattr(user, "calendar_feed_token", None) or "").strip()
    if token:
        return token
    for _ in range(5):
        candidate = new_calendar_feed_token()
        updated = (
            type(user)
            .objects.filter(pk=user.pk)
            .filter(Q(calendar_feed_token__isnull=True) | Q(calendar_feed_token=""))
            .update(calendar_feed_token=candidate)
        )
        if updated:
            user.calendar_feed_token = candidate
            return candidate
        user.refresh_from_db(fields=["calendar_feed_token"])
        token = (user.calendar_feed_token or "").strip()
        if token:
            return token
    # Collision improbable : forcer une valeur unique.
    candidate = new_calendar_feed_token()
    user.calendar_feed_token = candidate
    user.save(update_fields=["calendar_feed_token"])
    return candidate


def regenerate_calendar_feed_token(user) -> str:
    """Invalide l’ancien abonnement et renvoie un nouveau jeton."""
    candidate = new_calendar_feed_token()
    user.calendar_feed_token = candidate
    user.save(update_fields=["calendar_feed_token"])
    return candidate


def event_allows_personal_calendar(event: Event) -> bool:
    """Dates confirmées non répétition uniquement."""
    if getattr(event, "statut", None) != Event.Statut.CONFIRME:
        return False
    if getattr(event, "is_rehearsal", False):
        return False
    return True


def event_calendar_window(
    event: Event, roadmap: EventRoadmap | None = None
) -> tuple[datetime, datetime]:
    """Fenêtre agenda : arrivée feuille de route si connue, sinon date_debut → date_fin."""
    debut = timezone.localtime(event.date_debut)
    start = debut
    if roadmap and roadmap.arrival_start:
        start = datetime.combine(
            debut.date(), roadmap.arrival_start, tzinfo=debut.tzinfo
        )

    if event.date_fin:
        end = timezone.localtime(event.date_fin)
    else:
        end = debut + _DEFAULT_DURATION

    if end <= start:
        end = start + _DEFAULT_DURATION
    return start, end


def _escape_text(value: str) -> str:
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold_line(line: str) -> str:
    """RFC 5545 : lignes ≤ 75 octets, repli CRLF + espace (sans couper un UTF-8)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts: list[bytes] = []
    while raw:
        if not parts:
            budget = 75
        else:
            budget = 74  # leading space counts in the 75-octet limit
        chunk = raw[:budget]
        while chunk and (chunk[-1] & 0xC0) == 0x80:
            chunk = chunk[:-1]
        if not chunk:
            chunk = raw[:budget]
        parts.append(chunk)
        raw = raw[len(chunk) :]
    out = parts[0]
    for part in parts[1:]:
        out += b"\r\n " + part
    return out.decode("utf-8")


def _fmt_utc(dt: datetime) -> str:
    return timezone.localtime(dt).astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ics_uid(event: Event) -> str:
    host = "jazz-orchestra-yonnais.fr"
    site = getattr(settings, "SITE_URL", "") or ""
    if "://" in site:
        host = site.split("://", 1)[1].split("/", 1)[0] or host
    return f"event-{event.pk}@joy.{host}"


def _detail_url(event: Event) -> str:
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    if event.is_rehearsal:
        path = reverse("repetitions:detail", kwargs={"pk": event.pk})
    else:
        path = reverse("planning:event_detail", kwargs={"pk": event.pk})
    return f"{base}{path}" if base else path


def _location(event: Event) -> str:
    return (event.lieu_affiche or "").strip()


def _description(event: Event, roadmap: EventRoadmap | None = None) -> str:
    lines: list[str] = []
    type_nom = getattr(getattr(event, "type", None), "nom", "") or ""
    if type_nom:
        lines.append(type_nom)

    debut = timezone.localtime(event.date_debut)
    lines.append(f"Début : {debut.strftime('%H:%M')}")
    if event.date_fin:
        fin = timezone.localtime(event.date_fin)
        lines.append(f"Fin : {fin.strftime('%H:%M')}")

    if roadmap:
        if roadmap.arrival_start or roadmap.arrival_end:
            arr = []
            if roadmap.arrival_start:
                arr.append(roadmap.arrival_start.strftime("%H:%M"))
            if roadmap.arrival_end:
                arr.append(roadmap.arrival_end.strftime("%H:%M"))
            lines.append(f"Arrivée : {' – '.join(arr)}")
        if roadmap.soundcheck_at:
            lines.append(f"Balances : {roadmap.soundcheck_at.strftime('%H:%M')}")
        if roadmap.ready_at:
            lines.append(f"Prêt à jouer : {roadmap.ready_at.strftime('%H:%M')}")
        if roadmap.dress_code:
            lines.append(f"Dress code : {roadmap.dress_code.strip()}")
        if roadmap.parking_info:
            lines.append(f"Parking : {roadmap.parking_info.strip()}")
        if roadmap.venue_extra:
            lines.append(roadmap.venue_extra.strip())

    if event.description:
        lines.append(event.description.strip())

    url = _detail_url(event)
    if url:
        lines.append(f"Détails : {url}")

    return "\n".join(line for line in lines if line)


def _vevent_lines(
    event: Event,
    *,
    roadmap: EventRoadmap | None = None,
    ics_status: str = "CONFIRMED",
    now: datetime | None = None,
) -> list[str]:
    start, end = event_calendar_window(event, roadmap)
    stamp = now or timezone.now()
    summary = event.titre or "Événement JOY"
    location = _location(event)
    description = _description(event, roadmap)
    url = _detail_url(event)
    status = (ics_status or "CONFIRMED").upper()
    if status not in ("CONFIRMED", "TENTATIVE", "CANCELLED"):
        status = "CONFIRMED"

    props = [
        "BEGIN:VEVENT",
        f"UID:{_ics_uid(event)}",
        f"DTSTAMP:{_fmt_utc(stamp)}",
        f"DTSTART:{_fmt_utc(start)}",
        f"DTEND:{_fmt_utc(end)}",
        f"SUMMARY:{_escape_text(summary)}",
        f"STATUS:{status}",
        "TRANSP:OPAQUE",
    ]
    if location:
        props.append(f"LOCATION:{_escape_text(location)}")
    if description:
        props.append(f"DESCRIPTION:{_escape_text(description)}")
    if url:
        props.append(f"URL:{url}")
    props.append("END:VEVENT")
    return props


def build_event_ics(
    event: Event,
    *,
    roadmap: EventRoadmap | None = None,
) -> str:
    """Construit un fichier VCALENDAR (CRLF) pour un événement confirmé."""
    if not event_allows_personal_calendar(event):
        raise ValueError(
            "Seuls les événements confirmés (hors répétitions) peuvent être exportés."
        )

    props = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Jazz Orchestra Yonnais//Planning//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        *_vevent_lines(event, roadmap=roadmap, ics_status="CONFIRMED"),
        "END:VCALENDAR",
    ]
    return "\r\n".join(_fold_line(p) for p in props) + "\r\n"


def build_calendar_feed(
    events: Iterable[Event],
    *,
    name: str,
    event_status_fn: Callable[[Event], str] | None = None,
    roadmaps: dict[int, EventRoadmap] | None = None,
) -> str:
    """VCALENDAR multi-événements pour abonnement (orchestre / mes dates)."""
    now = timezone.now()
    cal_name = (name or "JOY").strip() or "JOY"
    roadmaps = roadmaps or {}
    props = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Jazz Orchestra Yonnais//Planning//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_text(cal_name)}",
        "X-WR-TIMEZONE:Europe/Paris",
    ]
    for event in events:
        if not event_allows_personal_calendar(event):
            continue
        status = "CONFIRMED"
        if event_status_fn is not None:
            status = event_status_fn(event) or "CONFIRMED"
        props.extend(
            _vevent_lines(
                event,
                roadmap=roadmaps.get(event.pk),
                ics_status=status,
                now=now,
            )
        )
    props.append("END:VCALENDAR")
    return "\r\n".join(_fold_line(p) for p in props) + "\r\n"


def _non_rehearsal_confirmed_qs() -> QuerySet[Event]:
    """Concerts / dates confirmées, hors types répétition (flag + nom legacy)."""
    return (
        Event.objects.filter(statut=Event.Statut.CONFIRME, type__is_rehearsal=False)
        .exclude(
            Q(type__nom__icontains="répétition") | Q(type__nom__icontains="repetition")
        )
        .select_related("type", "venue")
        .order_by("date_debut", "pk")
    )


def _feed_window_start() -> datetime:
    return timezone.now() - _FEED_LOOKBACK


def orchestra_feed_events() -> list[Event]:
    """Tous les concerts confirmés (fenêtre : −30 j → futur)."""
    return list(
        _non_rehearsal_confirmed_qs().filter(date_debut__gte=_feed_window_start())
    )


def mine_feed_events(user) -> tuple[list[Event], dict[int, str]]:
    """
    Dates confirmées où l’utilisateur est invited / maybe / confirmed.
    Retourne (events, ics_status_par_pk).
    """
    parts = (
        EventParticipation.objects.filter(
            user=user,
            status__code__in=MINE_PARTICIPATION_CODES,
            event__statut=Event.Statut.CONFIRME,
            event__type__is_rehearsal=False,
            event__date_debut__gte=_feed_window_start(),
        )
        .exclude(
            Q(event__type__nom__icontains="répétition")
            | Q(event__type__nom__icontains="repetition")
        )
        .select_related("status", "event", "event__type", "event__venue")
        .order_by("event__date_debut", "event_id")
    )
    events: list[Event] = []
    status_map: dict[int, str] = {}
    seen: set[int] = set()
    for part in parts:
        event = part.event
        if event.pk in seen:
            continue
        seen.add(event.pk)
        code = getattr(part.status, "code", "") or ""
        status_map[event.pk] = "CONFIRMED" if code == "confirmed" else "TENTATIVE"
        events.append(event)
    return events, status_map


def roadmaps_for_events(events: Iterable[Event]) -> dict[int, EventRoadmap]:
    ids = [e.pk for e in events]
    if not ids:
        return {}
    return {
        r.event_id: r
        for r in EventRoadmap.objects.filter(event_id__in=ids).select_related("event")
    }


def ics_filename(event: Event) -> str:
    base = slugify(event.titre) or "evenement-joy"
    day = timezone.localtime(event.date_debut).strftime("%Y-%m-%d")
    return f"{base}-{day}.ics"


def google_calendar_url(
    event: Event, *, roadmap: EventRoadmap | None = None
) -> str:
    """Lien « Ajouter à Google Agenda » (template=action)."""
    start, end = event_calendar_window(event, roadmap)
    dates = f"{_fmt_utc(start)}/{_fmt_utc(end)}"
    params = [
        ("action", "TEMPLATE"),
        ("text", event.titre or "Événement JOY"),
        ("dates", dates),
    ]
    loc = _location(event)
    if loc:
        params.append(("location", loc))
    desc = _description(event, roadmap)
    if desc:
        params.append(("details", desc))
    query = "&".join(f"{k}={quote(v, safe='')}" for k, v in params)
    return f"https://calendar.google.com/calendar/render?{query}"


def absolute_ics_url(path: str) -> str:
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    return f"{base}{path}" if base else path


def webcal_url(https_url: str) -> str:
    if https_url.startswith("https://"):
        return "webcal://" + https_url[len("https://") :]
    if https_url.startswith("http://"):
        return "webcal://" + https_url[len("http://") :]
    return https_url
