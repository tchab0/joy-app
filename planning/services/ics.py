"""Export iCalendar (.ics) pour ajouter un événement confirmé à l’agenda perso."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import quote

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from events.models import Event
from planning.models import EventRoadmap

# Durée par défaut si date_fin absente (concert / répé).
_DEFAULT_DURATION = timedelta(hours=2)


def event_allows_personal_calendar(event: Event) -> bool:
    """Seules les dates confirmées (non annulées) partent vers l’agenda perso."""
    return getattr(event, "statut", None) == Event.Statut.CONFIRME


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


def build_event_ics(
    event: Event,
    *,
    roadmap: EventRoadmap | None = None,
) -> str:
    """Construit un fichier VCALENDAR (CRLF) pour un événement confirmé."""
    if not event_allows_personal_calendar(event):
        raise ValueError("Seuls les événements confirmés peuvent être exportés.")

    start, end = event_calendar_window(event, roadmap)
    now = timezone.now()
    summary = event.titre or "Événement JOY"
    location = _location(event)
    description = _description(event, roadmap)
    url = _detail_url(event)

    props = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Jazz Orchestra Yonnais//Planning//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{_ics_uid(event)}",
        f"DTSTAMP:{_fmt_utc(now)}",
        f"DTSTART:{_fmt_utc(start)}",
        f"DTEND:{_fmt_utc(end)}",
        f"SUMMARY:{_escape_text(summary)}",
        "STATUS:CONFIRMED",
        "TRANSP:OPAQUE",
    ]
    if location:
        props.append(f"LOCATION:{_escape_text(location)}")
    if description:
        props.append(f"DESCRIPTION:{_escape_text(description)}")
    if url:
        props.append(f"URL:{url}")
    props.extend(["END:VEVENT", "END:VCALENDAR"])

    return "\r\n".join(_fold_line(p) for p in props) + "\r\n"


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
