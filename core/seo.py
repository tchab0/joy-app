"""Helpers SEO : JSON-LD, URLs canoniques, robots noindex."""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.urls import reverse


NOINDEX_PREFIXES = (
    "/compte/",
    "/planning/",
    "/repertoire/",
    "/chat/",
    "/stats/",
    "/admin/",
    "/admin-",
    "/administration/",
    "/feedback/",
    "/medias/proposer/",
)


def site_url() -> str:
    return getattr(settings, "SITE_URL", "https://jazz-orchestra-yonnais.fr").rstrip("/")


def absolute_url(path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{site_url()}{path}"


def path_should_noindex(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in NOINDEX_PREFIXES)


def _social_same_as() -> list[str]:
    urls: list[str] = []
    for key in (
        "SOCIAL_FACEBOOK_URL",
        "SOCIAL_INSTAGRAM_URL",
        "SOCIAL_YOUTUBE_URL",
        "SOCIAL_LINKABAND_URL",
    ):
        value = (getattr(settings, key, "") or "").strip()
        if value and value not in urls:
            urls.append(value)
    return urls


def music_group_jsonld() -> dict[str, Any]:
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "MusicGroup",
        "@id": f"{site_url()}/#musicgroup",
        "name": "Jazz Orchestra Yonnais",
        "alternateName": "JOY",
        "description": (
            "Big Band associatif basé à La Roche-sur-Yon (Vendée). "
            "Jazz, swing, concerts, festivals et prestations pour mariages, "
            "galas et entreprises."
        ),
        "url": f"{site_url()}/",
        "email": getattr(settings, "ADMIN_EMAIL", "admin@jazz-orchestra-yonnais.fr"),
        "genre": ["Jazz", "Swing", "Big Band"],
        "logo": absolute_url("/static/users/icons/logo-joy.webp"),
        "image": absolute_url("/static/users/icons/og-image.jpg"),
        "address": {
            "@type": "PostalAddress",
            "streetAddress": getattr(
                settings, "ORG_STREET_ADDRESS", "51 Rue de la Vergne"
            ),
            "postalCode": getattr(settings, "ORG_POSTAL_CODE", "85000"),
            "addressLocality": "La Roche-sur-Yon",
            "addressRegion": "Vendée",
            "addressCountry": "FR",
        },
        "areaServed": [
            {"@type": "AdministrativeArea", "name": "Vendée"},
            {"@type": "AdministrativeArea", "name": "Pays de la Loire"},
        ],
    }
    phone = (getattr(settings, "ORG_TELEPHONE", "") or "").strip()
    if phone:
        data["telephone"] = phone
    same_as = _social_same_as()
    if same_as:
        data["sameAs"] = same_as
    return data


def website_jsonld() -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "@id": f"{site_url()}/#website",
        "name": "Jazz Orchestra Yonnais",
        "url": f"{site_url()}/",
        "inLanguage": "fr-FR",
        "publisher": {"@id": f"{site_url()}/#musicgroup"},
    }


def service_jsonld() -> dict[str, Any]:
    """Offre de prestation live (mariages, galas, entreprises)."""
    return {
        "@context": "https://schema.org",
        "@type": "Service",
        "@id": f"{site_url()}/prestations/#service",
        "name": "Prestation Big Band Jazz Orchestra Yonnais",
        "serviceType": "Prestation musicale live — big band jazz & swing",
        "description": (
            "Le Jazz Orchestra Yonnais propose des prestations live pour mariages, "
            "cocktails, soirées de gala et animations d'entreprise en Vendée et "
            "Pays de la Loire."
        ),
        "provider": {"@id": f"{site_url()}/#musicgroup"},
        "areaServed": [
            {"@type": "AdministrativeArea", "name": "Vendée"},
            {"@type": "AdministrativeArea", "name": "Pays de la Loire"},
        ],
        "url": f"{site_url()}/prestations/",
    }


def music_event_jsonld(event) -> dict[str, Any]:
    from django.utils import timezone as dj_tz

    debut = dj_tz.localtime(event.date_debut)
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "MusicEvent",
        "name": event.titre,
        "url": absolute_url(event.get_absolute_url()),
        "startDate": debut.isoformat(),
        "eventStatus": {
            "confirme": "https://schema.org/EventScheduled",
            "tentative": "https://schema.org/EventScheduled",
            "annule": "https://schema.org/EventCancelled",
        }.get(event.statut, "https://schema.org/EventScheduled"),
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "performer": {"@id": f"{site_url()}/#musicgroup"},
        "organizer": {"@id": f"{site_url()}/#musicgroup"},
    }
    if event.date_fin:
        data["endDate"] = dj_tz.localtime(event.date_fin).isoformat()
    if event.description:
        data["description"] = event.description
    venue = event.venue
    if venue:
        location: dict[str, Any] = {
            "@type": "Place",
            "name": venue.nom,
            "address": {
                "@type": "PostalAddress",
                "addressLocality": venue.ville,
                "addressCountry": "FR",
            },
        }
        if venue.adresse:
            location["address"]["streetAddress"] = venue.adresse
        if venue.latitude is not None and venue.longitude is not None:
            location["geo"] = {
                "@type": "GeoCoordinates",
                "latitude": float(venue.latitude),
                "longitude": float(venue.longitude),
            }
        data["location"] = location
    if event.url_billets:
        data["offers"] = {
            "@type": "Offer",
            "url": event.url_billets,
            "availability": "https://schema.org/InStock",
        }
    return data


def dumps_jsonld(*objects: dict[str, Any]) -> str:
    payload: Any
    if len(objects) == 1:
        payload = objects[0]
    else:
        payload = list(objects)
    # Escape < to avoid </script> breakout when embedded in HTML.
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )


STATIC_PUBLIC_PATHS = (
    ("home", {}),
    ("concerts", {}),
    ("medias", {}),
    ("prestations", {}),
    ("contact", {}),
    ("goodies", {}),
    ("don", {}),
    ("adhesion", {}),
    ("mentions_legales", {}),
)


def static_public_urls() -> list[str]:
    return [reverse(name, kwargs=kwargs) for name, kwargs in STATIC_PUBLIC_PATHS]
