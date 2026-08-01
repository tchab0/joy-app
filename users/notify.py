"""Notifications métier : inbox in-app + Web Push en priorité, e-mail en secours."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from django.conf import settings
from django.core.mail import send_mail
from django.db import OperationalError, ProgrammingError
from django.db.models import Q
from django.utils import timezone

from users.webpush import send_web_push, vapid_configured

logger = logging.getLogger(__name__)


def notify_users(
    users: Iterable,
    *,
    title: str,
    body: str,
    url: str = "",
    requires_response: bool = False,
    related_type: str = "",
    related_id: int | None = None,
) -> int:
    """
    Notifie chaque utilisateur : enregistre une notification in-app, puis
    push si abonnement actif, sinon e-mail.

    ``requires_response`` : invitation / sondage / relance (statut « non répondu »
    distinct de « non lu »).

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
    # Chemin relatif pour l’inbox ; URL absolue pour push / e-mail.
    relative_url = url or ""
    absolute_url = relative_url
    if relative_url.startswith("/"):
        absolute_url = f"{site}{relative_url}"

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
            _persist_inbox(
                user,
                title=title,
                body=body,
                url=relative_url,
                requires_response=requires_response,
                related_type=related_type,
                related_id=related_id,
            )
            if _notify_one(user, title=title, body=body, url=absolute_url):
                sent += 1
        except Exception:
            logger.exception("Échec notif user_id=%s", uid)
    return sent


def unread_notifications_for_user(
    user, *, limit: int = 50, total: int | None = None
) -> tuple[list, int]:
    """
    Notifications in-app non lues du destinataire (ordre plus récentes d’abord).

    Retourne ``(liste tronquée, total non lu)``. Tolère un schéma pas encore
    migré → ``([], 0)``.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return [], 0
    try:
        from users.models import UserNotification

        qs = UserNotification.objects.filter(user=user, read_at__isnull=True)
        if total is None:
            total = qs.count()
        return list(qs[:limit]), total
    except (ProgrammingError, OperationalError):
        logger.warning(
            "unread_notifications_for_user indisponible (migration ?) user_id=%s",
            getattr(user, "pk", None),
        )
        return [], 0


def unread_notification_count_for_user(user) -> int:
    """Compte les notifications non lues sans charger leur contenu."""
    if user is None or not getattr(user, "is_authenticated", False):
        return 0
    try:
        from users.models import UserNotification

        return UserNotification.objects.filter(user=user, read_at__isnull=True).count()
    except (ProgrammingError, OperationalError):
        logger.warning(
            "unread_notification_count_for_user indisponible (migration ?) user_id=%s",
            getattr(user, "pk", None),
        )
        return 0


def invalidate_nav_banner(user) -> None:
    """Invalide le résumé de navigation après une notification modifiée."""
    from users.nav_cache import invalidate_nav_banner_cache

    invalidate_nav_banner_cache(user)


def _is_chat_notification(item) -> bool:
    related = (getattr(item, "related_type", None) or "").strip()
    if related == "chat_msg":
        return True
    url = (getattr(item, "url", None) or "").strip()
    return url.startswith("/chat/")


def _chat_room_label(item) -> str:
    """Libellé salon depuis le titre notif (ex. « JOY — Salon orchestre »)."""
    title = (getattr(item, "title", None) or "").strip()
    for prefix in ("JOY — ", "JOY - ", "JOY – "):
        if title.startswith(prefix):
            label = title[len(prefix) :].strip()
            if label:
                return label
    if title and title != "JOY":
        return title
    return "Salon chat"


def group_unread_inbox_for_banner(notifications: list) -> dict:
    """
    Compacte l’inbox pour la bannière Coulisses.

    Chat → groupes par URL (lien vers chaque salon) + total + extrait du plus récent.
    Autres → liste courte (invitations, sondages…).
    """
    chat_by_url: dict[str, dict] = {}
    chat_order: list[str] = []
    other: list = []
    chat_total = 0

    for item in notifications:
        if _is_chat_notification(item):
            chat_total += 1
            url = (item.url or "").strip() or "/chat/"
            group = chat_by_url.get(url)
            if group is None:
                preview = (item.body or "").strip()
                if len(preview) > 120:
                    preview = preview[:117].rstrip() + "…"
                group = {
                    "url": url,
                    "label": _chat_room_label(item),
                    "count": 0,
                    "open_pk": item.pk,
                    "preview": preview,
                }
                chat_by_url[url] = group
                chat_order.append(url)
            group["count"] += 1
        else:
            other.append(item)

    return {
        "chat_groups": [chat_by_url[u] for u in chat_order],
        "chat_total": chat_total,
        "other": other,
    }


def mark_notifications_responded(
    user,
    *,
    related_type: str = "",
    related_id: int | None = None,
    related_any: list[tuple[str, int]] | None = None,
) -> int:
    """
    Marque comme répondues les notifications actionnables liées à un objet.

    ``related_any`` : liste de couples (type, id) en plus / à la place.
    """
    try:
        from users.models import UserNotification
    except Exception:
        return 0

    pairs: list[tuple[str, int]] = []
    if related_type and related_id:
        pairs.append((related_type, int(related_id)))
    if related_any:
        for t, i in related_any:
            if t and i:
                pairs.append((t, int(i)))
    if not pairs:
        return 0

    q = Q()
    for t, i in pairs:
        q |= Q(related_type=t, related_id=i)

    try:
        updated = (
            UserNotification.objects.filter(
                user=user,
                requires_response=True,
                responded_at__isnull=True,
            )
            .filter(q)
            .update(responded_at=timezone.now())
        )
        if updated:
            invalidate_nav_banner(user)
        return updated
    except (ProgrammingError, OperationalError):
        logger.warning(
            "mark_notifications_responded indisponible (migration ?) user_id=%s",
            getattr(user, "pk", None),
        )
        return 0


def _persist_inbox(
    user,
    *,
    title: str,
    body: str,
    url: str,
    requires_response: bool = False,
    related_type: str = "",
    related_id: int | None = None,
) -> None:
    """Crée la notification in-app ; tolère un schéma pas encore migré."""
    try:
        from users.models import UserNotification

        UserNotification.objects.create(
            user=user,
            title=title[:200],
            body=body,
            url=(url or "")[:500],
            requires_response=bool(requires_response),
            related_type=(related_type or "")[:20],
            related_id=related_id,
        )
        invalidate_nav_banner(user)
    except (ProgrammingError, OperationalError):
        logger.warning(
            "Inbox notifications indisponible (migration manquante ?) — "
            "user_id=%s",
            getattr(user, "pk", None),
        )


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
