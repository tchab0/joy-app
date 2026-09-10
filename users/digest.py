"""Envoi des récaps (chat + autres types) selon les fréquences utilisateur."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from django.db import OperationalError, ProgrammingError
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from users.notify import notify_users
from users.notify_prefs import (
    CHAT_RELATED_TYPES,
    TYPE_CHAT,
    DeliveryPolicy,
    digest_is_due,
    mark_policy_sent,
    pref_type_for_related,
    resolve_delivery,
)

logger = logging.getLogger(__name__)


@dataclass
class _UserDigestDraft:
    chat_rooms: list[tuple[str, int, int]] = field(default_factory=list)
    chat_updates: list = field(default_factory=list)  # (membership, max_id)
    inbox_items: list = field(default_factory=list)
    # (policy, membership|None, type_pref|None, notify_type)
    buckets: list[tuple] = field(default_factory=list)


def send_due_notification_digests(*, now=None, dry_run: bool = False) -> int:
    """
    Envoie les récaps dus (chat + inbox non chat).

    Retourne le nombre d’utilisateurs effectivement notifiés (push/e-mail).
    """
    now = now or timezone.now()
    drafts: dict[int, _UserDigestDraft] = defaultdict(_UserDigestDraft)
    users_by_id: dict = {}

    try:
        _collect_chat(drafts, users_by_id, now=now)
        _collect_inbox(drafts, users_by_id, now=now)
    except (ProgrammingError, OperationalError):
        logger.warning("Digests indisponibles (migration manquante ?)")
        return 0

    sent = 0
    for user_id, draft in drafts.items():
        user = users_by_id.get(user_id)
        if user is None:
            continue
        if not draft.chat_rooms and not draft.inbox_items:
            # Avancer curseurs chat (messages déjà notifiés en instantané)
            # et last_sent des seaux dus sans contenu.
            if not dry_run:
                _advance_chat_cursors(draft)
                _touch_due_buckets(user, draft, now=now)
            continue

        title, body, url = _compose_payload(draft)
        if dry_run:
            sent += 1
            continue

        n = notify_users(
            [user],
            title=title,
            body=body,
            url=url,
            related_type="chat" if draft.chat_rooms and not draft.inbox_items else "",
            force_immediate=True,
        )
        # Toujours avancer curseurs / last_sent : notify_users a déjà créé
        # l’inbox. Sans ça, un échec SMTP/push rejoue le même digest à l’infini.
        _advance_chat_cursors(draft)
        _touch_due_buckets(user, draft, now=now)
        if not n:
            logger.warning(
                "Échec digest push/e-mail user_id=%s (inbox créée, curseurs avancés)",
                user_id,
            )
            continue
        sent += 1
    return sent


def _collect_chat(drafts, users_by_id, *, now) -> None:
    from chat.models import ChatMembership, ChatMessage
    from chat.services import message_targets_instant_notify

    memberships = list(
        ChatMembership.objects.filter(
            subscribed=True,
            left_at__isnull=True,
            user__is_active=True,
        ).select_related("user", "room")
    )
    if not memberships:
        return

    user_ids = {m.user_id for m in memberships}
    type_prefs = _load_type_prefs(user_ids)

    for m in memberships:
        user = m.user
        users_by_id[user.pk] = user
        chat_pref = type_prefs.get(user.pk, {}).get(TYPE_CHAT)
        policy = resolve_delivery(
            user,
            TYPE_CHAT,
            room=m.room,
            membership=m,
            type_pref=chat_pref,
        )
        if not digest_is_due(
            policy.frequency,
            policy.hour,
            policy.weekday,
            policy.last_sent_at,
            now,
        ):
            continue

        qs = (
            ChatMessage.objects.filter(
                room_id=m.room_id,
                deleted_at__isnull=True,
                pk__gt=m.last_digested_message_id,
            )
            .exclude(author_id=user.pk)
            .select_related("reply_to")
        )
        msgs = list(qs.order_by("pk"))
        draft = drafts[user.pk]
        draft.buckets.append((policy, m, chat_pref, TYPE_CHAT))
        if not msgs:
            continue
        max_id = msgs[-1].pk
        digest_msgs = [
            msg
            for msg in msgs
            if not message_targets_instant_notify(
                msg, user.pk, username=user.username
            )
        ]
        draft.chat_updates.append((m, max_id))
        if digest_msgs:
            draft.chat_rooms.append((m.room.title, len(digest_msgs), m.room_id))


def _collect_inbox(drafts, users_by_id, *, now) -> None:
    from users.models import UserNotification

    unread = (
        UserNotification.objects.filter(
            user__is_active=True,
            read_at__isnull=True,
        )
        .filter(Q(requires_response=False) | Q(responded_at__isnull=True))
        .exclude(related_type__in=CHAT_RELATED_TYPES)
        .select_related("user")
        .order_by("user_id", "created_at")
    )

    pending_by_user: dict[int, list] = defaultdict(list)
    for item in unread:
        pending_by_user[item.user_id].append(item)
        users_by_id[item.user_id] = item.user

    if not pending_by_user:
        return

    type_prefs = _load_type_prefs(pending_by_user.keys())

    for user_id, items in pending_by_user.items():
        user = users_by_id[user_id]
        prefs = type_prefs.get(user_id, {})
        due_items = []
        seen_buckets: set[tuple] = set()

        def _register(policy: DeliveryPolicy, type_pref=None, ntype: str = "") -> None:
            if policy.is_realtime:
                return
            if not digest_is_due(
                policy.frequency,
                policy.hour,
                policy.weekday,
                policy.last_sent_at,
                now,
            ):
                return
            bucket_key = (policy.source, ntype if policy.source == "type" else "")
            if bucket_key in seen_buckets:
                return
            seen_buckets.add(bucket_key)
            drafts[user_id].buckets.append((policy, None, type_pref, ntype))

        # Seau défaut + overrides type dus (même sans nouvel item)
        _register(resolve_delivery(user, ""))
        for ntype, pref in prefs.items():
            _register(
                resolve_delivery(user, ntype, type_pref=pref),
                type_pref=pref,
                ntype=ntype,
            )

        for item in items:
            ntype = pref_type_for_related(item.related_type)
            type_pref = prefs.get(ntype) if ntype else None
            policy = resolve_delivery(user, ntype, type_pref=type_pref)
            if policy.is_realtime:
                continue
            if not digest_is_due(
                policy.frequency,
                policy.hour,
                policy.weekday,
                policy.last_sent_at,
                now,
            ):
                continue
            if policy.last_sent_at and item.created_at <= policy.last_sent_at:
                continue
            due_items.append(item)

        if due_items:
            drafts[user_id].inbox_items.extend(due_items)


def _load_type_prefs(user_ids) -> dict[int, dict]:
    from users.models import NotificationTypePref

    out: dict[int, dict] = defaultdict(dict)
    if not user_ids:
        return out
    for pref in NotificationTypePref.objects.filter(user_id__in=user_ids):
        out[pref.user_id][pref.notify_type] = pref
    return out


def _advance_chat_cursors(draft: _UserDigestDraft) -> None:
    for membership, max_id in draft.chat_updates:
        membership.last_digested_message_id = max_id
        membership.save(update_fields=["last_digested_message_id"])


def _touch_due_buckets(user, draft: _UserDigestDraft, *, now) -> None:
    seen: set[tuple] = set()
    for policy, membership, type_pref, notify_type in draft.buckets:
        if policy.is_realtime:
            continue
        key = (policy.source, getattr(membership, "pk", None), notify_type)
        if key in seen:
            continue
        seen.add(key)
        mark_policy_sent(
            user,
            policy,
            now=now,
            membership=membership,
            type_pref=type_pref,
            notify_type=notify_type,
        )


def _compose_payload(draft: _UserDigestDraft) -> tuple[str, str, str]:
    from chat.services import chat_room_url

    parts: list[str] = []
    chat_url = ""
    if draft.chat_rooms:
        total = sum(c for _, c, _ in draft.chat_rooms)
        labels = [f"{title} ({n})" for title, n, _ in draft.chat_rooms[:3]]
        extra = len(draft.chat_rooms) - 3
        rooms_txt = ", ".join(labels)
        if extra > 0:
            rooms_txt += f" +{extra}"
        parts.append(f"{total} nouveau(x) message(s) : {rooms_txt}.")
        if len(draft.chat_rooms) == 1:
            chat_url = chat_room_url(draft.chat_rooms[0][2])
        else:
            _, _, busiest = max(draft.chat_rooms, key=lambda item: item[1])
            chat_url = chat_room_url(busiest)

    for item in draft.inbox_items[:8]:
        preview = (item.body or "").strip()
        if len(preview) > 100:
            preview = preview[:97].rstrip() + "…"
        parts.append(f"• {item.title} — {preview}" if preview else f"• {item.title}")
    extra_inbox = len(draft.inbox_items) - 8
    if extra_inbox > 0:
        parts.append(f"• … et {extra_inbox} autre(s).")

    body = "\n".join(parts) if parts else "Nouvelles notifications."
    if draft.chat_rooms and not draft.inbox_items:
        title = "JOY — Chat"
        url = chat_url or reverse("account_notifications")
    elif draft.inbox_items and not draft.chat_rooms and len(draft.inbox_items) == 1:
        title = draft.inbox_items[0].title or "JOY — Notification"
        url = draft.inbox_items[0].url or reverse("account_notifications")
    else:
        title = "JOY — Récap notifications"
        url = reverse("account_notifications")
    return title, body, url
