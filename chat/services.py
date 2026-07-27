from __future__ import annotations

import logging
import mimetypes
import re
from pathlib import Path

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Prefetch, Q
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

logger = logging.getLogger(__name__)

ORCHESTRA_ROOM_TITLE = "Orchestre"
STAFF_ROOM_TITLE = "Staff"
CHAT_HISTORY_LIMIT = 100
# @identifiant : lettres unicode, chiffres, . _ -
MENTION_TOKEN_RE = re.compile(
    r"(?<![\w.])@([^\W\d_][\w.-]{0,49})",
    re.UNICODE,
)
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
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".zip",
}
CHAT_ALLOWED_CONTENT_PREFIXES = ("image/", "audio/", "video/")
CHAT_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/plain",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/zip",
    "application/x-zip-compressed",
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


def ensure_staff_room() -> ChatRoom:
    """Salon privé staff — un seul par instance, sans musiciens."""
    room, created = ChatRoom.objects.get_or_create(
        kind=ChatRoom.Kind.STAFF,
        defaults={"title": STAFF_ROOM_TITLE},
    )
    if room.title != STAFF_ROOM_TITLE:
        room.title = STAFF_ROOM_TITLE
        room.save(update_fields=["title"])
    if created:
        seed_staff_members(room)
    return room


def sync_user_to_staff_room(user) -> ChatMembership | None:
    """Ajoute un compte staff actif au salon Staff (alertes ON par défaut)."""
    if not user.is_active:
        return None
    if not (user.is_staff or user.is_superuser):
        return None
    room = ensure_staff_room()
    return add_member(room, user)


def seed_staff_members(room: ChatRoom) -> int:
    """Ajoute tous les comptes staff actifs au salon (alertes ON par défaut)."""
    staff_users = User.objects.filter(
        Q(is_staff=True) | Q(is_superuser=True),
        is_active=True,
    )
    n = 0
    for user in staff_users:
        add_member(room, user)
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
    if room.kind == ChatRoom.Kind.STAFF:
        return bool(user.is_superuser or user.is_staff)
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


def _author_display_name(message: ChatMessage) -> str:
    author = message.author
    if message.kind == ChatMessage.Kind.SYSTEM and not author:
        return "Système"
    if not author:
        return "Compte supprimé"
    return author.get_full_name() or author.username


def _reply_preview(message: ChatMessage) -> dict | None:
    parent = message.reply_to
    if parent is None:
        return None
    if parent.is_deleted:
        preview = "Message supprimé"
    elif parent.body:
        preview = parent.body.strip()
        if len(preview) > 120:
            preview = preview[:117].rstrip() + "…"
    elif parent.attachments.all():
        n = parent.attachments.count()
        preview = f"{n} pièces jointes" if n > 1 else "Pièce jointe"
    else:
        preview = "…"
    return {
        "id": parent.pk,
        "author_id": parent.author_id,
        "author_name": _author_display_name(parent),
        "author_username": parent.author.username if parent.author else "",
        "body_preview": preview,
        "deleted": parent.is_deleted,
    }


def replies_prefetch() -> Prefetch:
    """Réponses actives (non supprimées), chronologiques — pour éviter le N+1."""
    return Prefetch(
        "replies",
        queryset=ChatMessage.objects.filter(deleted_at__isnull=True)
        .order_by("created_at")
        .only("id", "reply_to_id", "created_at"),
        to_attr="active_replies",
    )


def _replies_meta(message: ChatMessage) -> dict:
    """
    Métadonnées pour sauter du parent vers ses réponses.
    Payload minimal : count + id de la 1re réponse (ordre created_at).
    """
    if hasattr(message, "active_replies"):
        replies = message.active_replies
    else:
        replies = list(
            message.replies.filter(deleted_at__isnull=True)
            .order_by("created_at")
            .only("id")
        )
    return {
        "replies_count": len(replies),
        "first_reply_id": replies[0].pk if replies else None,
    }


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
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        "author_id": author.pk if author else None,
        "author_name": _author_display_name(message),
        "author_username": author.username if author else "",
        "reply_to": _reply_preview(message),
        "attachments": [serialize_attachment(a) for a in message.attachments.all()],
    }
    data.update(_replies_meta(message))
    data.update(_reaction_payload(message, viewer))
    return data


def unread_messages_filter() -> Q:
    """
    Messages non lus relatifs à une ChatMembership (via room__messages).
    Un message modifié recompte si edited_at > last_read_at.
    """
    return Q(room__messages__deleted_at__isnull=True) & ~Q(
        room__messages__author_id=F("user_id")
    ) & (
        Q(last_read_at__isnull=True)
        | Q(room__messages__edited_at__gt=F("last_read_at"))
        | (
            Q(room__messages__edited_at__isnull=True)
            & Q(room__messages__created_at__gt=F("last_read_at"))
        )
    )


def serialize_mention_member(user) -> dict:
    name = (user.get_full_name() or "").strip() or user.username
    return {
        "id": user.pk,
        "username": user.username,
        "name": name,
    }


def room_mention_members(room: ChatRoom) -> list:
    """
    Candidats @mention pour l’autocomplete.
    Salons généraux : musiciens actifs (+ membres du salon).
    Salon Staff : uniquement comptes staff (pas tout l’orchestre).
    """
    User = get_user_model()
    if room.kind == ChatRoom.Kind.STAFF:
        q = Q(is_staff=True) | Q(is_superuser=True)
    else:
        q = Q(is_musician=True) | Q(
            chat_memberships__room=room,
            chat_memberships__left_at__isnull=True,
        )
    qs = User.objects.filter(is_active=True).filter(q).distinct()
    return list(qs.order_by("last_name", "first_name", "username")[:300])


def extract_mention_tokens(body: str) -> list[str]:
    if not body:
        return []
    return MENTION_TOKEN_RE.findall(body)


def resolve_mentioned_users(room: ChatRoom, body: str, *, exclude_user=None) -> list:
    """
    Résout les @username vers des utilisateurs mentionnables.
    Si la personne n’est pas encore membre du salon, elle y est ajoutée
    (pour pouvoir ouvrir le lien de la notification).
    """
    tokens = {t.lower() for t in extract_mention_tokens(body)}
    if not tokens:
        return []
    candidates = room_mention_members(room)
    exclude_id = getattr(exclude_user, "pk", None)
    matched = []
    seen: set[int] = set()
    for u in candidates:
        if not u.username or u.username.lower() not in tokens:
            continue
        if exclude_id and u.pk == exclude_id:
            continue
        if u.pk in seen:
            continue
        seen.add(u.pk)
        if room.kind == ChatRoom.Kind.STAFF and not (u.is_staff or u.is_superuser):
            continue
        if not user_can_access_room(u, room):
            # Événement / morceau : ajouter pour que la notif soit ouvrable
            try:
                add_member(room, u, subscribed=bool(getattr(u, "chat_auto_subscribe", True)))
            except Exception:
                logger.exception(
                    "Impossible d’ajouter %s au salon %s après @mention",
                    u.pk,
                    room.pk,
                )
                continue
        matched.append(u)
    return matched


def message_targets_instant_notify(
    message: ChatMessage,
    user_id: int,
    *,
    username: str = "",
) -> bool:
    """True si l’utilisateur a déjà reçu (ou devrait recevoir) une notif instantanée."""
    if message.author_id == user_id:
        return False
    if (
        message.reply_to_id
        and message.reply_to
        and message.reply_to.author_id == user_id
    ):
        return True
    tokens = {t.lower() for t in extract_mention_tokens(message.body or "")}
    if not tokens:
        return False
    uname = (username or "").strip()
    if not uname:
        User = get_user_model()
        try:
            uname = User.objects.only("username").get(pk=user_id).username
        except User.DoesNotExist:
            return False
    return bool(uname) and uname.lower() in tokens


def notify_chat_message_targets(message: ChatMessage) -> int:
    """
    Notification instantanée (push / e-mail / inbox) pour @mentions
    et auteur du message cité. L’auteur du message n’est jamais notifié.
    Ne lève jamais : les échecs sont logués.
    """
    if message.kind == ChatMessage.Kind.SYSTEM:
        return 0
    if message.is_deleted:
        return 0

    recipients: dict[int, object] = {}
    for u in resolve_mentioned_users(
        message.room,
        message.body or "",
        exclude_user=message.author,
    ):
        recipients[u.pk] = u

    parent = message.reply_to
    if (
        parent
        and parent.author_id
        and parent.author_id != message.author_id
        and parent.author is not None
        and parent.author.is_active
    ):
        recipients[parent.author_id] = parent.author

    # Filet de sécurité : jamais notifier l’auteur de son propre message
    if message.author_id:
        recipients.pop(message.author_id, None)

    if not recipients:
        return 0

    author_name = _author_display_name(message)
    room_title = message.room.title
    preview = (message.body or "").strip()
    if not preview:
        preview = "pièce jointe"
    if len(preview) > 140:
        preview = preview[:137].rstrip() + "…"
    url = reverse("chat:room", kwargs={"room_id": message.room_id})
    title = f"JOY — {room_title}"
    body = f"{author_name} vous a cité : {preview}"

    try:
        from users.notify import notify_users

        return notify_users(
            recipients.values(),
            title=title,
            body=body,
            url=url,
            related_type="chat_msg",
            related_id=message.pk,
        )
    except Exception:
        logger.exception(
            "Échec notif mention chat message_id=%s", message.pk
        )
        return 0


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
        ChatMessage.objects.select_related(
            "author", "related_proposal", "reply_to", "reply_to__author"
        )
        .prefetch_related("attachments", "reactions", "reply_to__attachments")
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


def resolve_reply_to(room: ChatRoom, reply_to_id) -> ChatMessage | None:
    """Valide un message parent dans le même salon (ignore si invalide / manquant)."""
    if not reply_to_id:
        return None
    try:
        reply_id = int(reply_to_id)
    except (TypeError, ValueError):
        return None
    parent = (
        ChatMessage.objects.filter(pk=reply_id, room=room)
        .select_related("author")
        .prefetch_related("attachments")
        .first()
    )
    if parent is None or parent.is_deleted:
        return None
    return parent


def post_message(
    *,
    room: ChatRoom,
    author,
    body: str = "",
    files=None,
    kind: str = ChatMessage.Kind.NORMAL,
    related_proposal=None,
    reply_to: ChatMessage | None = None,
    reply_to_id=None,
    broadcast: bool = True,
) -> ChatMessage:
    body = (body or "").strip()
    files = list(files or [])
    if not body and not files:
        raise ValueError("Message vide.")

    if reply_to is None and reply_to_id is not None:
        reply_to = resolve_reply_to(room, reply_to_id)
    elif reply_to is not None:
        if reply_to.room_id != room.pk or reply_to.is_deleted:
            reply_to = None

    max_bytes = getattr(settings, "CHAT_ATTACHMENT_MAX_BYTES", 25 * 1024 * 1024)
    max_count = getattr(settings, "CHAT_ATTACHMENT_MAX_COUNT", 20)
    if len(files) > max_count:
        raise ValueError(f"Maximum {max_count} pièces jointes par message.")
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
        reply_to=reply_to,
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
        ChatMessage.objects.select_related(
            "author", "related_proposal", "reply_to", "reply_to__author"
        )
        .prefetch_related("attachments", "reactions", "reply_to__attachments")
        .get(pk=message.pk)
    )
    # broadcast=False depuis le consumer ASGI : group_send doit être await
    # dans la boucle async (async_to_sync dans database_sync_to_async casse l’écho).
    if broadcast:
        broadcast_message(message)
    if kind == ChatMessage.Kind.NORMAL:
        notify_chat_message_targets(message)
    return message


def edit_message(
    *,
    message: ChatMessage,
    editor,
    body: str,
    files=None,
    remove_attachment_ids=None,
) -> ChatMessage:
    """
    Modifie le texte et/ou les pièces jointes d’un message (auteur uniquement).
    Met edited_at à maintenant → redevient non lu pour les autres
    (comparaison activity vs last_read_at).
    """
    body = (body or "").strip()
    files = list(files or [])
    remove_ids: set[int] = set()
    for raw in remove_attachment_ids or []:
        try:
            remove_ids.add(int(raw))
        except (TypeError, ValueError):
            continue

    if message.is_deleted:
        raise ValueError("Message supprimé.")
    if message.kind != ChatMessage.Kind.NORMAL:
        raise ValueError("Ce message ne peut pas être modifié.")
    if message.author_id != getattr(editor, "pk", None):
        raise ValueError("Seul l’auteur peut modifier ce message.")

    max_bytes = getattr(settings, "CHAT_ATTACHMENT_MAX_BYTES", 25 * 1024 * 1024)
    max_count = getattr(settings, "CHAT_ATTACHMENT_MAX_COUNT", 20)
    validated: list[tuple[object, str, str]] = []
    for f in files:
        if f.size > max_bytes:
            name = getattr(f, "name", "fichier")
            raise ValueError(f"Le fichier {name} dépasse la limite.")
        ext, content_type = _validate_chat_file(f)
        validated.append((f, ext, content_type))

    existing_ids = set(
        message.attachments.values_list("pk", flat=True)
    )
    remove_ids &= existing_ids
    remaining = len(existing_ids) - len(remove_ids) + len(validated)
    if remaining > max_count:
        raise ValueError(f"Maximum {max_count} pièces jointes par message.")
    if not body and remaining <= 0:
        raise ValueError("Message vide.")

    if remove_ids:
        for att in message.attachments.filter(pk__in=remove_ids):
            if att.file:
                att.file.delete(save=False)
            att.delete()

    for f, _ext, content_type in validated:
        ChatAttachment.objects.create(
            message=message,
            file=f,
            original_name=getattr(f, "name", "fichier")[:255],
            content_type=content_type,
            size=f.size,
        )

    message.body = body
    message.edited_at = timezone.now()
    message.save(update_fields=["body", "edited_at"])

    message = (
        ChatMessage.objects.select_related(
            "author", "related_proposal", "reply_to", "reply_to__author"
        )
        .prefetch_related("attachments", "reactions", "reply_to__attachments")
        .get(pk=message.pk)
    )
    broadcast_message_edit(message)
    notify_chat_message_targets(message)
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


def broadcast_message_edit(message: ChatMessage) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(
        message.room.channel_group,
        {
            "type": "chat.message_edit",
            "message": serialize_message(message),
        },
    )


def serialize_read_cursor(membership: ChatMembership) -> dict | None:
    """Curseur de lecture d’un membre (pour accusés de lecture côté client)."""
    if membership.last_read_at is None:
        return None
    user = membership.user
    name = ""
    if user is not None:
        name = (user.get_full_name() or "").strip() or user.username
    return {
        "user_id": membership.user_id,
        "name": name,
        "last_read_at": membership.last_read_at.isoformat(),
    }


def room_read_cursors(room: ChatRoom) -> list[dict]:
    """
    Curseurs de lecture des membres actifs du salon.
    Un message est « lu » par un membre si last_read_at >= activité du message
    (created_at, ou edited_at s’il a été modifié).
    """
    memberships = (
        ChatMembership.objects.filter(
            room=room,
            left_at__isnull=True,
            last_read_at__isnull=False,
        )
        .select_related("user")
        .order_by("user__last_name", "user__first_name", "user__username")
    )
    out: list[dict] = []
    for m in memberships:
        cursor = serialize_read_cursor(m)
        if cursor is not None:
            out.append(cursor)
    return out


def broadcast_read(room: ChatRoom, cursor: dict) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(
        room.channel_group,
        {
            "type": "chat.read",
            "cursor": cursor,
        },
    )


def mark_room_read(room: ChatRoom, user, *, broadcast: bool = False) -> dict | None:
    """
    Avance le watermark de lecture du membre.
    Si broadcast=True, notifie le salon (accusés de lecture live).
    Retourne le curseur sérialisé, ou None si pas de membership active.
    """
    now = timezone.now()
    updated = ChatMembership.objects.filter(
        room=room, user=user, left_at__isnull=True
    ).update(last_read_at=now)
    if not updated:
        return None
    try:
        membership = ChatMembership.objects.select_related("user").get(
            room=room, user=user, left_at__isnull=True
        )
    except ChatMembership.DoesNotExist:
        return None
    # last_read_at vient d’être mis à jour via QuerySet.update — recharger
    membership.last_read_at = now
    cursor = serialize_read_cursor(membership)
    if broadcast and cursor is not None:
        broadcast_read(room, cursor)
    return cursor


def ensure_staff_membership(room: ChatRoom, user) -> ChatMembership:
    """Staff sans membership : crée / réintègre (alertes ON par défaut)."""
    subscribed = bool(getattr(user, "chat_auto_subscribe", True))
    membership, _ = ChatMembership.objects.get_or_create(
        room=room,
        user=user,
        defaults={"subscribed": subscribed},
    )
    if membership.left_at:
        membership.rejoin(subscribed=subscribed)
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

    # Curseur avant mark_room_read : pour scroller vers le 1er non-lu à l’ouverture
    initial_last_read_at = (
        membership.last_read_at.isoformat()
        if membership and membership.last_read_at
        else None
    )
    mark_room_read(room, user, broadcast=True)
    history = list(
        reversed(
            list(
                ChatMessage.objects.filter(room=room)
                .select_related(
                    "author", "related_proposal", "reply_to", "reply_to__author"
                )
                .prefetch_related(
                    "attachments",
                    "reactions",
                    "reply_to__attachments",
                    replies_prefetch(),
                )
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
    api_edit_url = reverse("chat:api_edit", kwargs={"room_id": room.pk})
    # ?v=3 : Staff = staff only (no full orchestra in @ mentions)
    api_members_url = (
        reverse("chat:api_members", kwargs={"room_id": room.pk}) + "?v=3"
    )
    messages_data = [serialize_message(m, viewer=user) for m in history]
    mention_members = [
        serialize_mention_member(u) for u in room_mention_members(room)
    ]
    read_cursors = room_read_cursors(room)

    return {
        "room": room,
        "membership": membership,
        # Ne pas passer "messages" : collision avec django.contrib.messages
        # (base.html afficherait l’historique salon comme flash).
        "messages_data": messages_data,
        "messages_script_id": f"chat-messages-{room.pk}",
        "mention_members": mention_members,
        "mention_members_script_id": f"chat-members-{room.pk}",
        "read_cursors": read_cursors,
        "read_cursors_script_id": f"chat-reads-{room.pk}",
        "participation": participation,
        "show_leave_hint": show_leave_hint,
        "ws_url": ws_url,
        "api_send_url": api_send_url,
        "api_react_url": api_react_url,
        "api_edit_url": api_edit_url,
        "api_members_url": api_members_url,
        "api_read_url": reverse("chat:api_read", kwargs={"room_id": room.pk}),
        "current_user_id": user.pk,
        "initial_last_read_at": initial_last_read_at,
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
    ).exclude(author_id=membership.user_id)
    if membership.last_read_at:
        qs = qs.filter(
            Q(edited_at__gt=membership.last_read_at)
            | (
                Q(edited_at__isnull=True)
                & Q(created_at__gt=membership.last_read_at)
            )
        )
    return qs.count()
