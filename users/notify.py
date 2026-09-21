"""Notifications métier : inbox in-app + Web Push en priorité, e-mail en secours."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from django.conf import settings
from django.core.mail import send_mail
from django.db import OperationalError, ProgrammingError
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from users.webpush import send_web_push, vapid_configured

logger = logging.getLogger(__name__)

_CHAT_ROOM_URL_RE = re.compile(r"^/chat/(\d+)/")


def notify_users(
    users: Iterable,
    *,
    title: str,
    body: str,
    url: str = "",
    requires_response: bool = False,
    related_type: str = "",
    related_id: int | None = None,
    notify_type: str = "",
    room=None,
    force_immediate: bool = False,
) -> int:
    """
    Notifie chaque utilisateur : enregistre une notification in-app, puis
    push si abonnement actif, sinon e-mail — sauf si la fréquence choisie
    est un récap (dans ce cas l’inbox est créée tout de suite, l’alerte
    part au prochain créneau).

    ``requires_response`` : invitation / sondage / relance (statut « non répondu »
    distinct de « non lu »).

    ``force_immediate`` : ignore les préférences (@mentions chat, envoi de digest).

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

    delivery_type = (notify_type or related_type or "").strip()

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
            from users.notify_prefs import (
                is_staff_only_notify_type,
                user_is_staff_recipient,
            )

            if is_staff_only_notify_type(delivery_type) and not user_is_staff_recipient(
                user
            ):
                # Jamais d’alerte staff (absences, contact…) vers un musicien pur.
                continue
            notif = _persist_inbox(
                user,
                title=title,
                body=body,
                url=relative_url,
                requires_response=requires_response,
                related_type=related_type,
                related_id=related_id,
            )
            from users.notify_prefs import should_deliver_immediately

            if not should_deliver_immediately(
                user,
                delivery_type,
                room,
                force=force_immediate,
            ):
                continue
            push_url = relative_url
            if notif is not None:
                push_url = reverse("account_notification_open", args=[notif.pk])
            if _notify_one(
                user,
                title=title,
                body=body,
                url=absolute_url,
                push_url=push_url,
            ):
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

        qs = UserNotification.objects.filter(
            user=user, read_at__isnull=True, archived_at__isnull=True
        )
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

        return UserNotification.objects.filter(
            user=user, read_at__isnull=True, archived_at__isnull=True
        ).count()
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
    if related in {"chat_msg", "chat", "chat_reply", "chat_mention"}:
        return True
    url = (getattr(item, "url", None) or "").strip()
    return url.startswith("/chat/")


def is_staff_destined_notification(item) -> bool:
    """
    True pour les alertes / chats destinés au staff (teinte slate en UI).
    - Types staff_only (staff_alert, contact)
    - Salon chat Staff (titre / libellé)
    """
    from users.notify_prefs import is_staff_only_notify_type

    related = (getattr(item, "related_type", None) or "").strip()
    if is_staff_only_notify_type(related):
        return True
    url = (getattr(item, "url", None) or "").strip()
    if related == "feedback" and url.startswith("/admin-retours"):
        return True
    title = (getattr(item, "title", None) or "").strip().lower()
    if "présence annulée" in title:
        return True
    if _is_chat_notification(item):
        label = _chat_room_label(item).strip().lower()
        if label == "staff" or label.startswith("staff "):
            return True
        if "salon staff" in title:
            return True
    return False


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


def _chat_room_id_from_url(url: str) -> int | None:
    """Extrait l’id salon depuis ``/chat/<id>/…`` (query string OK)."""
    match = _CHAT_ROOM_URL_RE.match((url or "").strip())
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _chat_banner_kind_for_room(room) -> str:
    """
    Clé de teinte pour le point bannière (alignée sur les libellés liste chat).

    ``event`` sans événement lié = salon « Privé ».
    """
    kind = getattr(room, "kind", "") or ""
    if kind == "event" and not getattr(room, "event_id", None):
        return "private"
    if kind in {
        "orchestra",
        "rehearsals",
        "event",
        "thematic",
        "piece",
        "staff",
        "section",
    }:
        return kind
    return "chat"


def _chat_rooms_by_id(room_ids: set[int]) -> dict[int, object]:
    if not room_ids:
        return {}
    try:
        from chat.models import ChatRoom

        return {
            room.pk: room
            for room in ChatRoom.objects.filter(pk__in=room_ids).only(
                "pk", "kind", "event_id"
            )
        }
    except (ProgrammingError, OperationalError):
        logger.warning("Résolution kind salon chat indisponible (migration ?)")
        return {}
    except Exception:
        logger.exception("Échec résolution kind salon chat")
        return {}


_BANNER_DOT_LABELS = {
    "action": "à traiter",
    "staff": "staff",
    "event": "événements",
    "rehearsal": "répétitions",
    "info": "informations",
    "chat": "messages",
}


def _banner_dot_for_item(item) -> str:
    """Teinte du point selon le type (hors salon, déjà coloré par kind)."""
    related = (getattr(item, "related_type", None) or "").strip()
    if related in {"staff_alert", "contact"}:
        return "staff"
    if related == "feedback" and is_staff_destined_notification(item):
        return "staff"
    if getattr(item, "is_unanswered", False):
        return "staff" if is_staff_destined_notification(item) else "action"
    if related == "rehearsal":
        return "rehearsal"
    if related in {"event", "participation"}:
        return "event"
    if related in {"event_roadmap", "photos", "media"}:
        return "info"
    if related == "proposal":
        return "action"
    if is_staff_destined_notification(item):
        return "staff"
    return "chat"


def _truncate_preview(text: str, limit: int = 140) -> str:
    preview = (text or "").strip()
    if len(preview) > limit:
        return preview[: limit - 1].rstrip() + "…"
    return preview


def _bucket_by_dot(items: list) -> list[tuple[str, list]]:
    buckets: dict[str, list] = {}
    order: list[str] = []
    for item in items:
        dot = _banner_dot_for_item(item)
        if dot not in buckets:
            buckets[dot] = []
            order.append(dot)
        buckets[dot].append(item)
    return [(dot, buckets[dot]) for dot in order]


def _href_for_banner_items(items, *, is_chat: bool = False, room_id=None, url: str = "") -> str:
    if is_chat:
        if len(items) == 1:
            return reverse("account_notification_open", args=[items[0].pk])
        if room_id:
            return reverse("chat:room", args=[room_id])
        target = (url or "").split("?", 1)[0]
        if target.startswith("/chat/"):
            return target or reverse("chat:list")
        return reverse("chat:list")
    if len(items) == 1:
        return reverse("account_notification_open", args=[items[0].pk])
    return reverse("account_notifications")


def _chip(
    items,
    *,
    dot: str,
    label: str,
    is_chat: bool = False,
    is_staff: bool = False,
    room_id=None,
    url: str = "",
    qty: int | None = None,
    preview: str = "",
    kind: str = "",
) -> dict:
    count = len(items)
    show = count == 1
    display_qty = count if qty is None else qty
    if is_chat and not show:
        unit = "message non lu" if display_qty == 1 else "messages non lus"
        aria = f"{display_qty} {unit} — {label}"
    elif not show:
        type_label = _BANNER_DOT_LABELS.get(dot, "notifications")
        aria = f"{display_qty} notifications — {type_label}"
    else:
        aria = label
    return {
        "dot": dot,
        "kind": kind or dot,
        "count": count,
        "qty": display_qty,
        "label": label,
        "preview": preview if show else "",
        "show_content": show,
        "is_chat": is_chat,
        "is_staff": bool(is_staff or dot == "staff"),
        "href": _href_for_banner_items(
            items, is_chat=is_chat, room_id=room_id, url=url
        ),
        "aria": aria,
        "open_pk": items[0].pk,
        "room_id": room_id,
    }


def _banner_chips(*, action: list, chat_groups: list, other: list) -> list[dict]:
    chips: list[dict] = []
    for dot, items in _bucket_by_dot(action):
        chips.append(
            _chip(
                items,
                dot=dot,
                label=(items[0].title or "").strip() or "Notification",
                preview=_truncate_preview(items[0].body),
            )
        )
    for group in chat_groups:
        kind = group.get("kind") or "chat"
        dot = f"chat-{kind}" if kind and kind != "chat" else "chat"
        chips.append(
            _chip(
                _ChipItems(group),
                dot=dot,
                label=group.get("label") or "Salon",
                is_chat=True,
                is_staff=bool(group.get("is_staff")),
                room_id=group.get("room_id"),
                url=group.get("url") or "",
                qty=group.get("qty") or group.get("count") or 1,
                preview=group.get("preview") or "",
                kind=kind,
            )
        )
    for dot, items in _bucket_by_dot(other):
        chips.append(
            _chip(
                items,
                dot=dot,
                label=(items[0].title or "").strip() or "Notification",
                preview=_truncate_preview(items[0].body),
            )
        )
    return chips


class _ChipItems(list):
    """Vue liste minimale (pk) pour réutiliser ``_chip`` sur un groupe chat."""

    def __init__(self, group: dict):
        pks = group.get("pks") or []
        super().__init__([type("N", (), {"pk": pk})() for pk in pks] or [type("N", (), {"pk": group.get("open_pk")})()])


def _unread_messages_by_room(user, room_ids: set[int]) -> dict[int, int]:
    """Messages non lus par salon (membership), pas le nombre de notifications."""
    ids = {rid for rid in room_ids if rid}
    if user is None or not ids:
        return {}
    try:
        from chat.models import ChatMembership
        from chat.services import unread_counts_for_memberships

        memberships = list(
            ChatMembership.objects.filter(
                user=user, room_id__in=ids, left_at__isnull=True
            )
        )
        by_membership = unread_counts_for_memberships(memberships)
        return {m.room_id: by_membership.get(m.pk, 0) for m in memberships}
    except (ProgrammingError, OperationalError):
        logger.warning("Compteurs non-lus salon indisponibles (migration ?)")
        return {}
    except Exception:
        logger.exception("Échec compteurs non-lus salon")
        return {}


def group_unread_inbox_for_banner(notifications: list) -> dict:
    """
    Compacte l’inbox pour la bannière Coulisses.

    Actions (sondage / invitation / événement confirmé à répondre) d’abord,
    puis chat groupé (avec ``kind`` pour la teinte du point), puis le reste.
    """
    chat_by_url: dict[str, dict] = {}
    chat_order: list[str] = []
    action: list = []
    other: list = []
    chat_total = 0
    room_ids: set[int] = set()

    for item in notifications:
        if _is_chat_notification(item):
            chat_total += 1
            url = (item.url or "").strip() or "/chat/"
            room_id = _chat_room_id_from_url(url)
            # Même salon même si l’URL porte ?msg= / ?thread= : un seul groupe.
            key = f"room:{room_id}" if room_id is not None else url.split("?", 1)[0]
            group = chat_by_url.get(key)
            if group is None:
                preview = (item.body or "").strip()
                if len(preview) > 120:
                    preview = preview[:117].rstrip() + "…"
                room_id = _chat_room_id_from_url(url)
                if room_id is not None:
                    room_ids.add(room_id)
                group = {
                    "url": url.split("?", 1)[0] or "/chat/",
                    "label": _chat_room_label(item),
                    "count": 0,
                    "open_pk": item.pk,
                    "pks": [],
                    "preview": preview,
                    "is_staff": is_staff_destined_notification(item),
                    "room_id": room_id,
                    "kind": "chat",
                    "show_content": False,
                    "qty": 0,
                    "unread_messages": 0,
                }
                chat_by_url[key] = group
                chat_order.append(key)
            group["count"] += 1
            group["pks"].append(item.pk)
        elif getattr(item, "is_unanswered", False):
            action.append(item)
        else:
            other.append(item)

    rooms = _chat_rooms_by_id(room_ids)
    for group in chat_by_url.values():
        room = rooms.get(group.get("room_id")) if group.get("room_id") else None
        if room is None:
            continue
        kind = _chat_banner_kind_for_room(room)
        group["kind"] = kind
        if kind == "staff":
            group["is_staff"] = True

    chat_groups = [chat_by_url[u] for u in chat_order]
    viewer = notifications[0].user if notifications else None
    unread_by_room = _unread_messages_by_room(
        viewer, {g["room_id"] for g in chat_groups if g.get("room_id")}
    )
    for group in chat_groups:
        unread = unread_by_room.get(group.get("room_id") or 0, 0)
        group["unread_messages"] = unread
        group["qty"] = unread or group["count"]
        group["show_content"] = group["count"] == 1
        if not group["show_content"]:
            group["preview"] = ""

    return {
        "action": action,
        "chat_groups": chat_groups,
        "chat_total": chat_total,
        "other": other,
        "chips": _banner_chips(
            action=action,
            chat_groups=chat_groups,
            other=other,
        ),
    }


def mark_chat_room_notifications_read(user, room_id: int) -> int:
    """Marque lues les notifications inbox qui pointent vers ce salon."""
    if user is None or not getattr(user, "is_authenticated", False) or not room_id:
        return 0
    prefix = f"/chat/{int(room_id)}/"
    try:
        from users.models import UserNotification

        updated = UserNotification.objects.filter(
            user=user,
            read_at__isnull=True,
            archived_at__isnull=True,
            url__startswith=prefix,
        ).update(read_at=timezone.now())
    except (ProgrammingError, OperationalError):
        logger.warning(
            "mark_chat_room_notifications_read indisponible user_id=%s",
            getattr(user, "pk", None),
        )
        return 0
    if updated:
        invalidate_nav_banner(user)
    return updated


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
):
    """Crée la notification in-app ; tolère un schéma pas encore migré."""
    try:
        from users.models import UserNotification

        notif = UserNotification.objects.create(
            user=user,
            title=title[:200],
            body=body,
            url=(url or "")[:500],
            requires_response=bool(requires_response),
            related_type=(related_type or "")[:20],
            related_id=related_id,
        )
        invalidate_nav_banner(user)
        return notif
    except (ProgrammingError, OperationalError):
        logger.warning(
            "Inbox notifications indisponible (migration manquante ?) — "
            "user_id=%s",
            getattr(user, "pk", None),
        )
        return None


def _relative_push_url(url: str) -> str:
    """Chemin relatif sûr pour le service worker (jamais d’URL absolue)."""
    target = (url or "/").strip() or "/"
    site = getattr(settings, "SITE_URL", "https://jazz-orchestra-yonnais.fr").rstrip(
        "/"
    )
    if target.startswith(site):
        target = target[len(site) :] or "/"
    if not target.startswith("/") or target.startswith("//"):
        target = "/"
    return target


def _plain_body_for_push(body: str) -> str:
    """Markdown léger → texte brut (lisibilité push / e-mail texte)."""
    import re

    text = body or ""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\+\+([^+]+)\+\+", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"\1", text)
    text = re.sub(r"^#{1,3}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*•]\s+", "• ", text, flags=re.MULTILINE)
    return text.strip()


def _notify_one(
    user, *, title: str, body: str, url: str, push_url: str = ""
) -> bool:
    rel_push = _relative_push_url(push_url or url)
    plain = _plain_body_for_push(body)
    if _try_push(user, title=title, body=plain, url=rel_push):
        return True
    return _try_email(user, title=title, body=plain, url=url)


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
    if not getattr(settings, "EMAIL_SENDING_ENABLED", True):
        logger.info(
            "E-mail en pause — pas de fallback mail user_id=%s",
            getattr(user, "pk", None),
        )
        return False
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
