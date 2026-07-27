"""Prévisions météo pour les concerts (Open-Meteo, sans clé API)."""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "JazzOrchestraYonnais/1.0 (https://jazz-orchestra-yonnais.fr; admin@jazz-orchestra-yonnais.fr)"

FORECAST_DAYS = 16
UNRELIABLE_AFTER_DAYS = 7
CACHE_TTL_FORECAST = 2 * 3600  # 2 h
CACHE_TTL_GEOCODE = 7 * 24 * 3600  # 7 j
CACHE_TTL_MISS = 30 * 60  # éviter de marteler l’API
HTTP_TIMEOUT = 4


def _safe_cache_key(prefix: str, *parts: object) -> str:
    raw = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"{prefix}:{digest}"


# Codes WMO → libellé FR court
_WMO_LABELS: dict[int, str] = {
    0: "Ciel clair",
    1: "Peu nuageux",
    2: "Partiellement nuageux",
    3: "Couvert",
    45: "Brouillard",
    48: "Brouillard givrant",
    51: "Bruine légère",
    53: "Bruine",
    55: "Bruine forte",
    56: "Bruine verglaçante",
    57: "Bruine verglaçante",
    61: "Pluie légère",
    63: "Pluie",
    65: "Pluie forte",
    66: "Pluie verglaçante",
    67: "Pluie verglaçante",
    71: "Neige légère",
    73: "Neige",
    75: "Neige forte",
    77: "Neige en grains",
    80: "Averses légères",
    81: "Averses",
    82: "Averses fortes",
    85: "Averses de neige",
    86: "Averses de neige",
    95: "Orage",
    96: "Orage et grêle",
    99: "Orage et grêle",
}

# Codes WMO → famille d’icône CSS (sun / cloud / rain / snow / storm / fog)
def _icon_kind(code: int) -> str:
    if code == 0:
        return "sun"
    if code in (1, 2):
        return "cloud-sun"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    if code >= 51:
        return "rain"
    return "cloud"


def _is_concert(event) -> bool:
    nom = (getattr(getattr(event, "type", None), "nom", None) or "").strip().lower()
    return "concert" in nom


def attach_weather(events, *, concerts_only: bool = False) -> None:
    """Attache ``event.weather`` (dict ou None) sur chaque événement."""
    for event in events:
        if concerts_only and not _is_concert(event):
            event.weather = None
            continue
        event.weather = forecast_for_event(event)


def cached_forecast_for_event(event) -> dict[str, Any] | None:
    """Lit seulement le cache météo/géocodage, sans requête HTTP."""
    venue = getattr(event, "venue", None)
    if not venue or not event.date_debut:
        return None

    local_dt = timezone.localtime(event.date_debut)
    now = timezone.localtime()
    if local_dt < now - timedelta(hours=1):
        return None
    if (local_dt.date() - now.date()).days > FORECAST_DAYS:
        return None

    coords = _cached_coords(venue)
    if not coords:
        return None
    lat, lng = coords
    hour_key = local_dt.strftime("%Y-%m-%dT%H")
    cached = cache.get(_safe_cache_key("weather", f"{lat:.2f}", f"{lng:.2f}", hour_key))
    return cached if cached else None


def forecast_for_event(event) -> dict[str, Any] | None:
    venue = getattr(event, "venue", None)
    if not venue or not event.date_debut:
        return None

    local_dt = timezone.localtime(event.date_debut)
    now = timezone.localtime()
    if local_dt < now - timedelta(hours=1):
        return None
    if (local_dt.date() - now.date()).days > FORECAST_DAYS:
        return None

    coords = _resolve_coords(venue)
    if not coords:
        return None

    lat, lng = coords
    return get_forecast(lat, lng, local_dt)


def _cached_coords(venue) -> tuple[float, float] | None:
    if venue.latitude is not None and venue.longitude is not None:
        return float(venue.latitude), float(venue.longitude)
    query_parts = [p for p in (venue.adresse, venue.ville, "France") if p]
    if not venue.ville:
        return None
    cached = cache.get(_safe_cache_key("geocode", " ".join(query_parts).strip().lower()))
    return tuple(cached) if cached else None


def get_forecast(lat: float, lng: float, local_dt: datetime) -> dict[str, Any] | None:
    """Prévision horaire la plus proche de ``local_dt`` (fuseau Europe/Paris)."""
    hour_key = local_dt.strftime("%Y-%m-%dT%H")
    cache_key = _safe_cache_key("weather", f"{lat:.2f}", f"{lng:.2f}", hour_key)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached if cached else None

    result = _fetch_forecast(lat, lng, local_dt)
    cache.set(cache_key, result if result is not None else False, CACHE_TTL_FORECAST if result else CACHE_TTL_MISS)
    return result


def _resolve_coords(venue) -> tuple[float, float] | None:
    if venue.latitude is not None and venue.longitude is not None:
        return float(venue.latitude), float(venue.longitude)

    query_parts = [p for p in (venue.adresse, venue.ville, "France") if p]
    if not venue.ville:
        return None
    return _geocode(" ".join(query_parts))


def _geocode(query: str) -> tuple[float, float] | None:
    cache_key = _safe_cache_key("geocode", query.strip().lower())
    cached = cache.get(cache_key)
    if cached is not None:
        return tuple(cached) if cached else None

    params = urllib.parse.urlencode(
        {"format": "json", "limit": "1", "q": query}
    )
    url = f"{NOMINATIM_URL}?{params}"
    try:
        data = _http_json(url)
    except Exception:
        logger.warning("Géocodage Nominatim échoué pour %r", query, exc_info=True)
        cache.set(cache_key, False, CACHE_TTL_MISS)
        return None

    if not data:
        cache.set(cache_key, False, CACHE_TTL_GEOCODE)
        return None

    try:
        lat = float(data[0]["lat"])
        lng = float(data[0]["lon"])
    except (KeyError, IndexError, TypeError, ValueError):
        cache.set(cache_key, False, CACHE_TTL_MISS)
        return None

    cache.set(cache_key, (lat, lng), CACHE_TTL_GEOCODE)
    return lat, lng


def _fetch_forecast(lat: float, lng: float, local_dt: datetime) -> dict[str, Any] | None:
    params = urllib.parse.urlencode(
        {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lng:.4f}",
            "hourly": "temperature_2m,weather_code,precipitation_probability,wind_speed_10m",
            "timezone": "Europe/Paris",
            "forecast_days": str(FORECAST_DAYS),
            "wind_speed_unit": "kmh",
        }
    )
    url = f"{OPEN_METEO_URL}?{params}"
    try:
        data = _http_json(url)
    except Exception:
        logger.warning("Open-Meteo indisponible pour %s,%s", lat, lng, exc_info=True)
        return None

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None

    target = local_dt.replace(minute=0, second=0, microsecond=0)
    best_i = None
    best_delta = None
    for i, t in enumerate(times):
        try:
            slot = datetime.fromisoformat(t)
        except ValueError:
            continue
        if timezone.is_naive(slot):
            slot = timezone.make_aware(slot, timezone.get_current_timezone())
        delta = abs((slot - target).total_seconds())
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_i = i

    # Pas de créneau à plus de 90 min de l’heure du concert
    if best_i is None or best_delta is None or best_delta > 90 * 60:
        return None

    temps = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []
    precip = hourly.get("precipitation_probability") or []
    winds = hourly.get("wind_speed_10m") or []

    try:
        temp = temps[best_i]
        code = int(codes[best_i]) if codes[best_i] is not None else 0
    except (IndexError, TypeError, ValueError):
        return None

    if temp is None:
        return None

    precip_prob = None
    try:
        if precip[best_i] is not None:
            precip_prob = int(precip[best_i])
    except (IndexError, TypeError, ValueError):
        pass

    wind_kmh = None
    try:
        if winds[best_i] is not None:
            wind_kmh = round(float(winds[best_i]))
    except (IndexError, TypeError, ValueError):
        pass

    now = timezone.localtime()
    days_ahead = (target.date() - now.date()).days
    unreliable = days_ahead >= UNRELIABLE_AFTER_DAYS

    slot_dt = datetime.fromisoformat(times[best_i])
    if timezone.is_naive(slot_dt):
        slot_dt = timezone.make_aware(slot_dt, timezone.get_current_timezone())

    return {
        "temp_c": round(float(temp)),
        "code": code,
        "label": _WMO_LABELS.get(code, "Variable"),
        "icon": _icon_kind(code),
        "precip_prob": precip_prob,
        "wind_kmh": wind_kmh,
        "at_hour": slot_dt.strftime("%Hh"),
        "unreliable": unreliable,
    }


def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status}")
        return json.loads(resp.read().decode())
