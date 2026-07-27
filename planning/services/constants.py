"""Constantes planning."""
from __future__ import annotations

from planning.models import ParticipationStatus

STATUS_CODES = {
    "invited": {"label": "Invité", "color_token": "warning", "sort_order": 10},
    "confirmed": {"label": "Confirmé", "color_token": "success", "sort_order": 20},
    "maybe": {"label": "Peut-être", "color_token": "warning", "sort_order": 25},
    "declined": {"label": "Refusé", "color_token": "danger", "sort_order": 30},
    "replacement_needed": {
        "label": "Remplacement demandé",
        "color_token": "neutral",
        "sort_order": 40,
    },
}

RESPOND_MAP = {
    "yes": "confirmed",
    "no": "declined",
    "maybe": "maybe",
}


_STATUS_CACHE: dict[str, ParticipationStatus] | None = None

# Matériel collectif utile à un big band (hors instruments / matos perso).
DEFAULT_BIG_BAND_EQUIPMENT: list[tuple[str, str, int]] = [
    ("Pupitre chef", "Scène", 10),
    ("Pupitres musiciens (lot)", "Scène", 20),
    ("Chaise / tabouret chef", "Scène", 30),
    ("Tapis antidérapant scène", "Scène", 40),
    ("Système de sonorisation (PA)", "Sono", 50),
    ("Table de mixage", "Sono", 60),
    ("Enceintes façade", "Sono", 70),
    ("Retours de scène", "Sono", 80),
    ("Micro chant", "Sono", 90),
    ("Micros section / ambiance", "Sono", 100),
    ("Pieds de micro", "Sono", 110),
    ("Câbles XLR", "Sono", 120),
    ("Multipaire / snake", "Sono", 130),
    ("Boîtes de direct (DI)", "Sono", 140),
    ("Multiprise / rallonge", "Sono", 150),
    ("Partition chef (pad)", "Partitions", 160),
    ("Classeurs / partitions orchestre", "Partitions", 170),
    ("Véhicule transport", "Transport", 180),
    ("Chariot / diable", "Transport", 190),
    ("Gaffer / scotch scène", "Divers", 200),
    ("Signalétique / affiche concert", "Divers", 210),
]

EQUIPMENT_CATEGORIES: tuple[str, ...] = tuple(
    dict.fromkeys(cat for _, cat, _ in DEFAULT_BIG_BAND_EQUIPMENT)
)



