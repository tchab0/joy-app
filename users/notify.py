"""Notifications métier : Web Push en priorité, e-mail en secours."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from django.conf import settings
from django.core.mail import send_mail

from users.webpush import send_web_push, vapid_configured

logger = logging.getLogger(__name__)


def notify_users(
    users: Iterable,
    *,
    title: str,
    body: str,
    url: str = "",
) -> int:
    """
    Notifie chaque utilisateur : push si abonnement actif, sinon e-mail.

    Retourne le nombre d’utilisateurs notifiés (push ou e-mail).
    Les échecs sont logués, jamais levés.
    """
    title = (title or "").strip() or "JOY"
    body = (body or "").strip()
    if not body:
        return 0

    site = getattr(settings, "SITE_URL", "https://jazz-orchestra-yonnais.fr").rstrip(
        "/"
    )
    absolute_url = url
    if url and url.startswith("/"):
        absolute_url = f"{site}{url}"

    sent = 0
    seen: set[int] = set()
    for user in users:
        if user is None:
            continue
        uid = getattr(user, "pk", None)
        if uid is None or uid in seen:
            continue
        seen.add(uid)
        try:
            if _notify_one(user, title=title, body=body, url=absolute_url):
                sent += 1
        except Exception:
            logger.exception("Échec notif user_id=%s", uid)
    return sent


def _notify_one(user, *, title: str, body: str, url: str) -> bool:
    if _try_push(user, title=title, body=body, url=url):
        return True
    return _try_email(user, title=title, body=body, url=url)


def _try_push(user, *, title: str, body: str, url: str) -> bool:
    if not vapid_configured():
        return False
    from users.models import PushSubscription

    subs = list(PushSubscription.objects.filter(user_id=user.pk))
    if not subs:
        return False
    ok = False
    for sub in subs:
        if send_web_push(sub, title=title, body=body, url=url or "/"):
            ok = True
    return ok


def _try_email(user, *, title: str, body: str, url: str) -> bool:
    email = (getattr(user, "email", "") or "").strip()
    if not email:
        logger.info(
            "Pas de canal notif pour user_id=%s (ni push ni e-mail)",
            getattr(user, "pk", None),
        )
        return False
    message = body
    if url:
        message = f"{body}\n\n{url}"
    try:
        send_mail(
            subject=title,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception(
            "Échec e-mail notif user_id=%s", getattr(user, "pk", None)
        )
        return False
