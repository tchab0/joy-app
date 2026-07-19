"""Notifications SMS instantanées (invitations, lancement de sondage…)."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from users.phone import normalize_phone
from users.sms import send_sms

logger = logging.getLogger(__name__)


def notify_users_sms(users: Iterable, body: str) -> int:
    """
    Envoie un SMS immédiat aux utilisateurs ayant un téléphone normalisable.

    Retourne le nombre d’envois réussis. Les échecs sont logués, jamais levés
    (une notif SMS ne doit pas faire échouer l’action métier).
    """
    body = (body or "").strip()
    if not body:
        return 0

    sent = 0
    seen_phones: set[str] = set()
    for user in users:
        if user is None:
            continue
        raw = getattr(user, "phone", "") or ""
        phone = normalize_phone(raw)
        if not phone or phone in seen_phones:
            continue
        seen_phones.add(phone)
        try:
            send_sms(phone, body)
            sent += 1
        except Exception:
            logger.exception("Échec SMS instantané vers user_id=%s", getattr(user, "pk", None))
    return sent
