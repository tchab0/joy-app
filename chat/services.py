from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from chat.models import ChatAttachment, ChatMembership, ChatMessage, ChatRoom

ORCHESTRA_ROOM_TITLE = "Orchestre"


def ensure_orchestra_room() -> ChatRoom:
    room, _ = ChatRoom.objects.get_or_create(
        kind=ChatRoom.Kind.ORCHESTRA,
        defaults={"title": ORCHESTRA_ROOM_TITLE},
    )
    if room.title != ORCHESTRA_ROOM_TITLE:
        room.title = ORCHESTRA_ROOM_TITLE
        room.save(update_fields=["title"])
    return room


def ensure_event_room(event) -> ChatRoom:
    title = event.titre
    room, created = ChatRoom.objects.get_or_create(
        event=event,
        defaults={
            "kind": ChatRoom.Kind.EVENT,
            "title": title,
        },
    )
    updates: list[str] = []
    if room.kind != ChatRoom.Kind.EVENT:
        room.kind = ChatRoom.Kind.EVENT
        updates.append("kind")
    if room.title != title:
        room.title = title
        updates.append("title")
    if updates:
        room.save(update_fields=updates)
    return room


def add_member(
    room: ChatRoom,
    user,
    *,
    subscribed: bool | None = None,
    rejoin: bool = True,
) -> ChatMembership:
    if subscribed is None:
        subscribed = bool(getattr(user, "chat_auto_subscribe", True))
    membership, created = ChatMembership.objects.get_or_create(
        room=room,
        user=user,
        defaults={"subscribed": subscribed},
    )
    if not created and rejoin and membership.left_at is not None:
        membership.left_at = None
        membership.save(update_fields=["left_at"])
    return membership


def sync_musician_to_orchestra(user) -> ChatMembership | None:
    if not getattr(user, "is_musician", False) or not user.is_active:
        return None
    room = ensure_orchestra_room()
    return add_member(room, user)


def sync_participation_to_chat(participation) -> ChatMembership:
    room = ensure_event_room(participation.event)
    return add_member(room, participation.user)


def active_membership(room: ChatRoom, user) -> ChatMembership | None:
    try:
        membership = ChatMembership.objects.get(room=room, user=user)
    except ChatMembership.DoesNotExist:
        return None
    if membership.left_at is not None:
        return None
    return membership


def user_can_access_room(user, room: ChatRoom) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or user.is_staff:
        return True
    return active_membership(room, user) is not None


def serialize_attachment(att: ChatAttachment) -> dict:
    return {
        "id": att.pk,
        "name": att.original_name,
        "url": att.file.url if att.file else "",
        "content_type": att.content_type,
        "size": att.size,
        "is_image": att.is_image,
        "is_pdf": att.is_pdf,
    }


def serialize_message(message: ChatMessage) -> dict:
    author = message.author
    return {
        "id": message.pk,
        "body": "" if message.is_deleted else message.body,
        "deleted": message.is_deleted,
        "created_at": message.created_at.isoformat(),
        "author_id": author.pk if author else None,
        "author_name": (
            (author.get_full_name() or author.username) if author else "Compte supprimé"
        ),
        "attachments": [serialize_attachment(a) for a in message.attachments.all()],
    }


def broadcast_message(message: ChatMessage) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(
        message.room.channel_group,
        {
            "type": "chat.message",
            "message": serialize_message(message),
        },
    )


@transaction.atomic
def post_message(
    *,
    room: ChatRoom,
    author,
    body: str = "",
    files: list | None = None,
) -> ChatMessage:
    body = (body or "").strip()
    files = list(files or [])
    if not body and not files:
        raise ValueError("Message vide.")

    max_bytes = getattr(settings, "CHAT_ATTACHMENT_MAX_BYTES", 25 * 1024 * 1024)
    message = ChatMessage.objects.create(room=room, author=author, body=body)
    for f in files:
        if f.size > max_bytes:
            name = getattr(f, "name", "fichier")
            raise ValueError(f"Le fichier {name} dépasse la limite.")
        ChatAttachment.objects.create(
            message=message,
            file=f,
            original_name=getattr(f, "name", "fichier")[:255],
            content_type=getattr(f, "content_type", "") or "",
            size=f.size,
        )
    message = (
        ChatMessage.objects.select_related("author")
        .prefetch_related("attachments")
        .get(pk=message.pk)
    )
    broadcast_message(message)
    return message


def mark_room_read(room: ChatRoom, user) -> None:
    ChatMembership.objects.filter(room=room, user=user, left_at__isnull=True).update(
        last_read_at=timezone.now()
    )


def unread_count(membership: ChatMembership) -> int:
    qs = ChatMessage.objects.filter(
        room_id=membership.room_id, deleted_at__isnull=True
    )
    if membership.last_read_at:
        qs = qs.filter(created_at__gt=membership.last_read_at)
    qs = qs.exclude(author_id=membership.user_id)
    return qs.count()
