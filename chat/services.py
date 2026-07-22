from __future__ import annotations

import mimetypes
from pathlib import Path

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from chat.models import (
    ChatAttachment,
    ChatMembership,
    ChatMessage,
    ChatMessageReaction,
    ChatRoom,
)

ORCHESTRA_ROOM_TITLE = "Orchestre"
CHAT_HISTORY_LIMIT = 100
CHAT_ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".pdf",
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
    ".mp4",
    ".webm",
    ".txt",
    ".doc",
    ".docx",
}
CHAT_ALLOWED_CONTENT_PREFIXES = ("image/", "audio/", "video/")
CHAT_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/plain",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
User = get_user_model()


def ensure_orchestra_room() -> ChatRoom:
    room, _ = ChatRoom.objects.get_or_create(
        kind=ChatRoom.Kind.ORCHESTRA,
        defaults={"title": ORCHESTRA_ROOM_TITLE},
    )
    if room.title != ORCHESTRA_ROOM_TITLE:
        room.title = ORCHESTRA_ROOM_TITLE
        room.save(update_fields=["title"])
    return room


def seed_staff_members(room: ChatRoom) -> int:
    """Ajoute tous les comptes staff actifs au salon (salon staff-only initial)."""
    staff_users = User.objects.filter(
        Q(is_staff=True) | Q(is_superuser=True),
        is_active=True,
    )
    n = 0
    for user in staff_users:
        add_member(room, user, subscribed=False)
        n += 1
    return n


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
    if created:
        seed_staff_members(room)
    return room


def _chorus_system_body(piece) -> str:
    order = (piece.chorus_order or "").strip()
    if order:
        return f"Ordre des chorus (dernière décision) :\n{order}"
    return (
        "Salon du morceau — aucun ordre de chorus enregistré pour l’instant. "
        "Les remarques (intro / structure) sont sur la fiche du morceau."
    )


@transaction.atomic
def ensure_piece_room(piece) -> ChatRoom:
    """
    Crée (si besoin) le salon d’un morceau : staff seed + tous les musiciens actifs.
    Message système initial avec le récap chorus.
    """
    title = f"Morceau · {piece.title}"
    room, created = ChatRoom.objects.get_or_create(
        piece=piece,
        defaults={
            "kind": ChatRoom.Kind.PIECE,
            "title": title,
        },
    )
    updates: list[str] = []
    if room.kind != ChatRoom.Kind.PIECE:
        room.kind = ChatRoom.Kind.PIECE
        updates.append("kind")
    if room.title != title:
        room.title = title
        updates.append("title")
    if updates:
        room.save(update_fields=updates)

    if created:
        seed_staff_members(room)
        musicians = User.objects.filter(is_musician=True, is_active=True)
        for user in musicians:
            add_member(room, user)
        post_message(
            room=room,
            author=None,
            body=_chorus_system_body(piece),
            kind=ChatMessage.Kind.SYSTEM,
        )
    return room


def sync_musician_to_piece_rooms(user) -> int:
    """Ajoute un musicien à tous les salons morceau actifs."""
    if not getattr(user, "is_musician", False) or not user.is_active:
        return 0
    rooms = ChatRoom.objects.filter(kind=ChatRoom.Kind.PIECE, is_active=True)
    n = 0
    for room in rooms:
        add_member(room, user)
        n += 1
    return n


def notify_piece_chorus_update(piece, *, author=None) -> ChatMessage | None:
    """Poste un message système si le salon existe déjà."""
    try:
        room = piece.chat_room
    except ChatRoom.DoesNotExist:
        return None
    if not room.is_active:
        return None
    order = (piece.chorus_order or "").strip()
    body = (
        f"Nouvelle décision chorus :\n{order}"
        if order
        else "L’ordre des chorus a été effacé."
    )
    return post_message(
        room=room,
        author=author,
        body=body,
        kind=ChatMessage.Kind.SYSTEM,
    )


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
    url = ""
    if att.pk:
        url = reverse("chat:attachment", kwargs={"pk": att.pk})
    return {
        "id": att.pk,
        "name": att.original_name,
        "url": url,
        "content_type": att.content_type,
        "size": att.size,
        "is_image": att.is_image,
        "is_pdf": att.is_pdf,
    }


def _reaction_payload(message: ChatMessage, viewer=None) -> dict:
    """Compteurs / état perso (down = masquage local uniquement)."""
    reactions = list(message.reactions.all())
    likes = sum(1 for r in reactions if r.value == ChatMessageReaction.Value.UP)
    mine = None
    hidden = False
    if viewer is not None and getattr(viewer, "is_authenticated", False):
        for r in reactions:
            if r.user_id == viewer.pk:
                mine = r.value
                hidden = r.value == ChatMessageReaction.Value.DOWN
                break
    return {"likes": likes, "mine": mine, "hidden": hidden}


def serialize_message(message: ChatMessage, viewer=None) -> dict:
    author = message.author
    poll_url = ""
    if message.related_proposal_id and message.kind == ChatMessage.Kind.POLL_LAUNCH:
        poll_url = reverse(
            "planning:poll_detail", kwargs={"pk": message.related_proposal_id}
        )
    data = {
        "id": message.pk,
        "kind": message.kind,
        "highlight": message.kind == ChatMessage.Kind.POLL_LAUNCH,
        "poll_url": poll_url,
        "body": "" if message.is_deleted else message.body,
        "deleted": message.is_deleted,
        "created_at": message.created_at.isoformat(),
        "author_id": author.pk if author else None,
        "author_name": (
            "Système"
            if message.kind == ChatMessage.Kind.SYSTEM and not author
            else (
                (author.get_full_name() or author.username) if author else "Compte supprimé"
            )
        ),
        "attachments": [serialize_attachment(a) for a in message.attachments.all()],
    }
    data.update(_reaction_payload(message, viewer))
    return data


@transaction.atomic
def toggle_reaction(
    *,
    message: ChatMessage,
    user,
    value: str,
) -> dict:
    """
    Bascule une réaction (up/down). Même valeur = retrait.
    Retourne {likes, mine, hidden} pour le viewer.
    """
    if value not in {
        ChatMessageReaction.Value.UP,
        ChatMessageReaction.Value.DOWN,
    }:
        raise ValueError("Réaction invalide.")
    if message.is_deleted:
        raise ValueError("Message supprimé.")

    existing = (
        ChatMessageReaction.objects.select_for_update()
        .filter(message=message, user=user)
        .first()
    )
    if existing and existing.value == value:
        existing.delete()
    elif existing:
        existing.value = value
        existing.save(update_fields=["value", "updated_at"])
    else:
        ChatMessageReaction.objects.create(message=message, user=user, value=value)

    message = (
        ChatMessage.objects.select_related("author", "related_proposal")
        .prefetch_related("attachments", "reactions")
        .get(pk=message.pk)
    )
    payload = _reaction_payload(message, user)
    broadcast_reaction(message.room, message.pk, payload["likes"])
    return payload


def broadcast_reaction(room: ChatRoom, message_id: int, likes: int) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(
        room.channel_group,
        {
            "type": "chat.reaction",
            "message_id": message_id,
            "likes": likes,
        },
    )


def _validate_chat_file(f) -> tuple[str, str]:
    """Return (safe_ext, content_type) or raise ValueError."""
    name = getattr(f, "name", "fichier") or "fichier"
    ext = Path(name).suffix.lower()
    if ext not in CHAT_ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Type de fichier non autorisé ({ext or 'sans extension'}). "
            f"Acceptés : {', '.join(sorted(CHAT_ALLOWED_EXTENSIONS))}"
        )
    content_type = (getattr(f, "content_type", "") or "").split(";")[0].strip().lower()
    guessed, _ = mimetypes.guess_type(f"x{ext}")
    if not content_type or content_type == "application/octet-stream":
        content_type = guessed or "application/octet-stream"
    ok = content_type in CHAT_ALLOWED_CONTENT_TYPES or any(
        content_type.startswith(p) for p in CHAT_ALLOWED_CONTENT_PREFIXES
    )
    # SVG / HTML never allowed even if client claims image/*
    if ext in {".svg", ".html", ".htm", ".js", ".xhtml"} or content_type in {
        "image/svg+xml",
        "text/html",
        "application/javascript",
        "text/javascript",
    }:
        raise ValueError("Type de fichier non autorisé.")
    if not ok:
        raise ValueError(f"Type MIME non autorisé ({content_type or 'inconnu'}).")
    return ext, content_type


def post_message(
    *,
    room: ChatRoom,
    author,
    body: str = "",
    files=None,
    kind: str = ChatMessage.Kind.NORMAL,
    related_proposal=None,
) -> ChatMessage:
    body = (body or "").strip()
    files = list(files or [])
    if not body and not files:
        raise ValueError("Message vide.")

    max_bytes = getattr(settings, "CHAT_ATTACHMENT_MAX_BYTES", 25 * 1024 * 1024)
    validated: list[tuple[object, str, str]] = []
    for f in files:
        if f.size > max_bytes:
            name = getattr(f, "name", "fichier")
            raise ValueError(f"Le fichier {name} dépasse la limite.")
        ext, content_type = _validate_chat_file(f)
        validated.append((f, ext, content_type))

    message = ChatMessage.objects.create(
        room=room,
        author=author,
        body=body,
        kind=kind,
        related_proposal=related_proposal,
    )
    for f, _ext, content_type in validated:
        ChatAttachment.objects.create(
            message=message,
            file=f,
            original_name=getattr(f, "name", "fichier")[:255],
            content_type=content_type,
            size=f.size,
        )
    message = (
        ChatMessage.objects.select_related("author", "related_proposal")
        .prefetch_related("attachments", "reactions")
        .get(pk=message.pk)
    )
    broadcast_message(message)
    return message


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


def mark_room_read(room: ChatRoom, user) -> None:
    ChatMembership.objects.filter(room=room, user=user, left_at__isnull=True).update(
        last_read_at=timezone.now()
    )


def ensure_staff_membership(room: ChatRoom, user) -> ChatMembership:
    """Staff sans membership : crée / réintègre (non abonné aux notifications par défaut)."""
    membership, _ = ChatMembership.objects.get_or_create(
        room=room,
        user=user,
        defaults={"subscribed": False},
    )
    if membership.left_at:
        membership.rejoin(subscribed=False)
    return membership


def build_room_embed_context(request: HttpRequest, room: ChatRoom) -> dict:
    """
    Contexte partagé salon chat (page dédiée ou embed poll).
    Prérequis : l'utilisateur a déjà accès (membre actif ou staff).
    """
    user = request.user
    is_staff = user.is_staff or user.is_superuser
    membership = active_membership(room, user)
    if membership is None and is_staff:
        membership = ensure_staff_membership(room, user)

    mark_room_read(room, user)
    history = list(
        reversed(
            list(
                ChatMessage.objects.filter(room=room)
                .select_related("author", "related_proposal")
                .prefetch_related("attachments", "reactions")
                .order_by("-created_at")[:CHAT_HISTORY_LIMIT]
            )
        )
    )

    participation = None
    show_leave_hint = False
    draft_proposal = None
    invite_musicians: list = []
    invite_choices: list = []
    open_proposal = None
    lock_options: list = []

    if room.event_id:
        participation = (
            user.event_participations.filter(event_id=room.event_id)
            .select_related("status")
            .first()
        )
        if participation and participation.status.code == "declined":
            show_leave_hint = True
        if is_staff:
            from planning.models import DateProposal
            from planning.services import (
                draft_proposal_for_event,
                invite_musicians_for_form,
            )

            draft_proposal = draft_proposal_for_event(room.event)
            open_proposal = (
                DateProposal.objects.filter(
                    linked_event_id=room.event_id,
                    status=DateProposal.Status.OPEN,
                )
                .prefetch_related("options")
                .first()
            )
            if open_proposal:
                lock_options = list(
                    open_proposal.options.order_by("sort_order", "starts_at")
                )
            already = set(
                room.event.participations.values_list("user_id", flat=True)
            )
            invite_users = list(
                User.objects.filter(is_musician=True, is_active=True)
                .exclude(pk__in=already)
                .select_related("musician_profile")
                .order_by("last_name", "first_name")[:200]
            )
            invite_musicians = invite_musicians_for_form(invite_users)
            invite_choices = invite_musicians  # truthy check in templates

    ws_scheme = "wss" if request.is_secure() else "ws"
    ws_url = f"{ws_scheme}://{request.get_host()}/ws/chat/{room.pk}/"
    api_send_url = reverse("chat:api_send", kwargs={"room_id": room.pk})
    api_react_url = reverse("chat:api_react", kwargs={"room_id": room.pk})
    messages_data = [serialize_message(m, viewer=user) for m in history]

    return {
        "room": room,
        "membership": membership,
        "messages": history,
        "messages_data": messages_data,
        "messages_script_id": f"chat-messages-{room.pk}",
        "participation": participation,
        "show_leave_hint": show_leave_hint,
        "ws_url": ws_url,
        "api_send_url": api_send_url,
        "api_react_url": api_react_url,
        "current_user_id": user.pk,
        "is_planning_staff": is_staff,
        "draft_proposal": draft_proposal,
        "invite_musicians": invite_musicians,
        "invite_choices": invite_choices,
        "open_proposal": open_proposal,
        "lock_options": lock_options,
        "embedded": True,
        "show_chat_chrome": False,
    }


def unread_count(membership: ChatMembership) -> int:
    qs = ChatMessage.objects.filter(
        room_id=membership.room_id, deleted_at__isnull=True
    )
    if membership.last_read_at:
        qs = qs.filter(created_at__gt=membership.last_read_at)
    qs = qs.exclude(author_id=membership.user_id)
    return qs.count()
