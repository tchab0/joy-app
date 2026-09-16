from __future__ import annotations

import logging
import mimetypes
import re
from datetime import timedelta
from pathlib import Path

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, F, Prefetch, Q
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
REHEARSALS_ROOM_TITLE = "Répétitions"
STAFF_ROOM_TITLE = "Staff"
CHAT_HISTORY_LIMIT = 100
# Salon Orchestre : messages déjà lus (par personne) et plus vieux qu’un mois.
ORCHESTRA_ARCHIVE_AFTER = timedelta(days=30)
CHAT_ARCHIVE_PAGE = 50
CHAT_ARCHIVE_AROUND = 25

# Salons pupitre : familles d’instruments (chant associée à tous).
# Clés = codes OrchestraSection (sauf chant, présente dans tous les salons).
# Clés stables → section_key sur ChatRoom.
SECTION_ROOM_DEFS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "sax",
        "Saxophones",
        frozenset(
            {
                "alto_1",
                "alto_2",
                "tenor_1",
                "tenor_2",
                "baryton",
            }
        ),
    ),
    (
        "trompettes",
        "Trompettes & clarinette",
        frozenset(
            {
                "trompette_1",
                "trompette_2",
                "trompette_3",
                "trompette_4",
                "clarinette",
            }
        ),
    ),
    (
        "trombones",
        "Trombones",
        frozenset(
            {
                "trombone_1",
                "trombone_2",
                "trombone_3",
                "trombone_4",
            }
        ),
    ),
    (
        "rythmique",
        "Rythmique",
        frozenset(
            {
                "piano",
                "guitare",
                "basse",
                "batterie",
                "percussion",
            }
        ),
    ),
)
SECTION_ROOM_BY_KEY = {key: (title, postes) for key, title, postes in SECTION_ROOM_DEFS}
CHANT_POSTE = "chant"
# @identifiant simple (username) : lettres unicode, chiffres, . _ -
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


def seed_musician_members(room: ChatRoom) -> int:
    """Ajoute tous les musiciens actifs au salon."""
    musicians = User.objects.filter(is_musician=True, is_active=True)
    n = 0
    for user in musicians:
        add_member(room, user)
        n += 1
    return n


def ensure_rehearsals_room() -> ChatRoom:
    """Salon unique pour toutes les répétitions (propositions setlist, discussion)."""
    room, created = ChatRoom.objects.get_or_create(
        kind=ChatRoom.Kind.REHEARSALS,
        defaults={"title": REHEARSALS_ROOM_TITLE},
    )
    updates: list[str] = []
    if room.title != REHEARSALS_ROOM_TITLE:
        room.title = REHEARSALS_ROOM_TITLE
        updates.append("title")
    if not room.is_active:
        room.is_active = True
        updates.append("is_active")
    if updates:
        room.save(update_fields=updates)
    if created:
        seed_staff_members(room)
        seed_musician_members(room)
    ensure_rehearsal_setlist_tip(room)
    return room


def sync_musician_to_rehearsals_room(user) -> ChatMembership | None:
    """Ajoute un musicien actif au salon Répétitions."""
    if not getattr(user, "is_musician", False) or not user.is_active:
        return None
    room = ensure_rehearsals_room()
    return add_member(room, user)


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


REHEARSAL_SETLIST_TIP_PREFIX = "Proposez ici les morceaux à travailler"


def _rehearsal_setlist_tip_body() -> str:
    return (
        f"{REHEARSAL_SETLIST_TIP_PREFIX}. "
        "Les autres votent avec 👍. "
        "Le staff compose ensuite la setlist."
    )


def _mark_digested_through(room: ChatRoom, message_id: int) -> None:
    """Avance last_digested_message_id pour ne pas alerter sur un message auto."""
    if not message_id:
        return
    ChatMembership.objects.filter(
        room=room,
        left_at__isnull=True,
        last_digested_message_id__lt=message_id,
    ).update(last_digested_message_id=message_id)


def _rehearsal_setlist_tip_id(room: ChatRoom) -> int | None:
    return (
        ChatMessage.objects.filter(
            room=room,
            kind=ChatMessage.Kind.SYSTEM,
            body__startswith=REHEARSAL_SETLIST_TIP_PREFIX,
            deleted_at__isnull=True,
        )
        .order_by("-pk")
        .values_list("pk", flat=True)
        .first()
    )


def ensure_rehearsal_setlist_tip(room: ChatRoom) -> ChatMessage | None:
    """
    Message système (idempotent) pour rappeler aux musiciens de proposer
    des morceaux et de voter avec 👍 dans le salon Répétitions.

    Ne déclenche pas de digest « nouveau message » : le tip reste visible
    dans le salon, mais n’envoie pas d’alerte push/e-mail à lui seul.
    """
    if room.kind != ChatRoom.Kind.REHEARSALS:
        return None
    existing_id = _rehearsal_setlist_tip_id(room)
    if existing_id:
        _mark_digested_through(room, existing_id)
        return None
    msg = post_message(
        room=room,
        author=None,
        body=_rehearsal_setlist_tip_body(),
        kind=ChatMessage.Kind.SYSTEM,
        require_thread=False,
    )
    if msg is not None:
        _mark_digested_through(room, msg.pk)
    return msg


def _rehearsal_thread_opener_body(event) -> str:
    from django.utils.formats import date_format

    local_dt = timezone.localtime(event.date_debut)
    when = f"{date_format(local_dt, 'l j F Y')} · {date_format(local_dt, 'G:i')}"
    return (
        f"{REHEARSAL_THREAD_OPENER_PREFIX} du {when}. "
        "Proposez des morceaux ici — les autres votent avec 👍. "
        "Le staff compose ensuite la setlist."
    )


def ensure_rehearsal_thread_opener(event) -> ChatMessage | None:
    """Message système d’ouverture du fil pour une date de répétition."""
    if not getattr(event, "is_rehearsal", False):
        return None
    room = ensure_rehearsals_room()
    existing = (
        ChatMessage.objects.filter(
            room=room,
            thread_event_id=event.pk,
            kind=ChatMessage.Kind.SYSTEM,
            body__startswith=REHEARSAL_THREAD_OPENER_PREFIX,
            deleted_at__isnull=True,
        )
        .order_by("pk")
        .first()
    )
    if existing:
        return None
    msg = post_message(
        room=room,
        author=None,
        body=_rehearsal_thread_opener_body(event),
        kind=ChatMessage.Kind.SYSTEM,
        thread_event=event,
        require_thread=False,
        broadcast=True,
    )
    if msg is not None:
        _mark_digested_through(room, msg.pk)
    return msg


def resolve_rehearsal_thread_event(room: ChatRoom, thread_event_id) -> object | None:
    """Valide un Event répétition pour le salon Répétitions."""
    if room.kind != ChatRoom.Kind.REHEARSALS or not thread_event_id:
        return None
    try:
        event_id = int(thread_event_id)
    except (TypeError, ValueError):
        return None
    from events.models import Event

    event = (
        Event.objects.select_related("venue", "type", "rehearsal_plan")
        .filter(pk=event_id)
        .first()
    )
    if event is None or not getattr(event, "is_rehearsal", False):
        return None
    return event


def thread_unread_count(
    room_id: int,
    user_id: int,
    thread_event_id: int | None,
    last_read_at,
) -> int:
    qs = ChatMessage.objects.filter(
        room_id=room_id,
        deleted_at__isnull=True,
        thread_event_id=thread_event_id,
    ).exclude(author_id=user_id)
    if last_read_at:
        qs = qs.filter(
            Q(edited_at__gt=last_read_at)
            | (Q(edited_at__isnull=True) & Q(created_at__gt=last_read_at))
        )
    return qs.count()


def serialize_rehearsal_thread(
    event,
    *,
    room: ChatRoom,
    user,
    last_read_at=None,
    n_setlist: int | None = None,
) -> dict:
    """Carte d’un fil répétition pour la liste du salon."""
    from django.db.models import Count

    msg_stats = (
        ChatMessage.objects.filter(
            room=room,
            thread_event_id=event.pk,
            deleted_at__isnull=True,
        )
        .exclude(
            kind=ChatMessage.Kind.SYSTEM,
            body__startswith=REHEARSAL_THREAD_OPENER_PREFIX,
        )
        .aggregate(
            n=Count("id"),
        )
    )
    last = (
        ChatMessage.objects.filter(
            room=room,
            thread_event_id=event.pk,
            deleted_at__isnull=True,
        )
        .exclude(
            kind=ChatMessage.Kind.SYSTEM,
            body__startswith=REHEARSAL_THREAD_OPENER_PREFIX,
        )
        .select_related("author")
        .order_by("-created_at")
        .first()
    )
    if n_setlist is None:
        n_setlist = 0
        plan = getattr(event, "rehearsal_plan", None)
        if plan is not None and hasattr(plan, "items"):
            try:
                n_setlist = plan.items.count()
            except Exception:
                n_setlist = 0

    preview = ""
    if last and last.body:
        preview = last.body.strip()
        if len(preview) > 100:
            preview = preview[:97].rstrip() + "…"
    elif last and last.attachments.exists():
        preview = "Pièce jointe"

    local_dt = timezone.localtime(event.date_debut)
    unread = 0
    if user is not None and getattr(user, "is_authenticated", False):
        unread = thread_unread_count(room.pk, user.pk, event.pk, last_read_at)

    from django.utils.formats import date_format

    when_label = (
        f"{date_format(local_dt, 'D j b')} · {date_format(local_dt, 'G:i')}"
    )

    return {
        "event_id": event.pk,
        "title": event.titre,
        "when_label": when_label,
        "date_iso": local_dt.date().isoformat(),
        "is_past": event.date_debut < timezone.now(),
        "venue": event.lieu_affiche if getattr(event, "venue_id", None) else "",
        "n_messages": int(msg_stats["n"] or 0),
        "n_setlist": int(n_setlist or 0),
        "last_preview": preview,
        "last_at": last.created_at.isoformat() if last else None,
        "unread": unread,
        "url": chat_room_url(room.pk, thread_event_id=event.pk),
        "detail_url": reverse("repetitions:detail", kwargs={"pk": event.pk}),
        "setlist_url": reverse("repetitions:detail", kwargs={"pk": event.pk}),
    }


def _rehearsal_thread_events(room: ChatRoom):
    """
    Événements répétition affichés dans le salon :
    à venir + passé récent (45 j), et dates plus anciennes déjà discutées.
    """
    from datetime import timedelta

    from events.models import Event

    now = timezone.now()
    cutoff = now - timedelta(days=45)

    events = list(
        Event.objects.filter(type__is_rehearsal=True, date_debut__gte=cutoff)
        .select_related("venue", "type", "rehearsal_plan")
        .order_by("date_debut")
    )
    event_ids = {e.pk for e in events}

    older_with_msgs = (
        Event.objects.filter(
            type__is_rehearsal=True,
            date_debut__lt=cutoff,
            chat_thread_messages__room=room,
            chat_thread_messages__deleted_at__isnull=True,
        )
        .select_related("venue", "type", "rehearsal_plan")
        .distinct()
        .order_by("date_debut")
    )
    for e in older_with_msgs:
        if e.pk not in event_ids:
            events.append(e)
            event_ids.add(e.pk)

    events.sort(key=lambda e: e.date_debut)
    return events


def partition_rehearsal_threads(
    room: ChatRoom, user
) -> tuple[list[dict], list[dict]]:
    """
    Fils du salon Répétitions : (actifs à venir, archivés passés).
    Les passés restent consultables dans Archives (plus récents en premier).
    """
    if room.kind != ChatRoom.Kind.REHEARSALS:
        return [], []

    from django.db.models import Count
    from repetitions.models import RehearsalPlan

    membership = active_membership(room, user) if user else None
    last_read_at = membership.last_read_at if membership else None
    events = _rehearsal_thread_events(room)
    event_ids = {e.pk for e in events}

    plan_counts = {
        row["event_id"]: row["n"]
        for row in RehearsalPlan.objects.filter(event_id__in=event_ids)
        .annotate(n=Count("items"))
        .values("event_id", "n")
    }

    active: list[dict] = []
    archived: list[dict] = []
    for e in events:
        card = serialize_rehearsal_thread(
            e,
            room=room,
            user=user,
            last_read_at=last_read_at,
            n_setlist=plan_counts.get(e.pk, 0),
        )
        if card["is_past"]:
            archived.append(card)
        else:
            active.append(card)

    archived.reverse()  # plus récent passé en premier
    return active, archived


def list_rehearsal_threads(room: ChatRoom, user) -> list[dict]:
    """Fils actifs (répétitions à venir) du salon Répétitions."""
    active, _archived = partition_rehearsal_threads(room, user)
    return active


def ensure_event_room(event) -> ChatRoom:
    """
    Salon lié à un événement (concerts, etc.).
    Les répétitions utilisent le salon unique « Répétitions ».
    """
    if getattr(event, "is_rehearsal", False):
        return ensure_rehearsals_room()

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
    if not hasattr(room, "event") or room.event_id != event.pk:
        room.event = event
    return room


def deactivate_rehearsal_event_rooms() -> int:
    """Désactive les anciens salons EVENT liés à une répétition."""
    qs = ChatRoom.objects.filter(kind=ChatRoom.Kind.EVENT, event__isnull=False)
    to_deactivate = []
    for room in qs.select_related("event", "event__type"):
        if getattr(room.event, "is_rehearsal", False) and room.is_active:
            to_deactivate.append(room.pk)
    if not to_deactivate:
        return 0
    return ChatRoom.objects.filter(pk__in=to_deactivate).update(is_active=False)


def chat_room_url(
    room_id: int,
    *,
    message_id: int | None = None,
    thread_event_id: int | None = None,
) -> str:
    """Chemin relatif vers un salon, optionnellement un fil répé / un message."""
    from urllib.parse import urlencode

    path = reverse("chat:room", kwargs={"room_id": room_id})
    params: dict[str, int] = {}
    if thread_event_id is not None:
        params["thread"] = int(thread_event_id)
    if message_id is not None:
        params["msg"] = int(message_id)
    if params:
        return f"{path}?{urlencode(params)}"
    return path


REHEARSAL_THREAD_OPENER_PREFIX = "Discussion de la répétition"


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


def ensure_section_room(section_key: str) -> ChatRoom:
    """Crée / aligne un salon pupitre (titre figé depuis SECTION_ROOM_DEFS)."""
    if section_key not in SECTION_ROOM_BY_KEY:
        raise ValueError(f"Clé pupitre inconnue : {section_key}")
    title, _postes = SECTION_ROOM_BY_KEY[section_key]
    room, created = ChatRoom.objects.get_or_create(
        kind=ChatRoom.Kind.SECTION,
        section_key=section_key,
        defaults={"title": title},
    )
    updates: list[str] = []
    if room.kind != ChatRoom.Kind.SECTION:
        room.kind = ChatRoom.Kind.SECTION
        updates.append("kind")
    if room.section_key != section_key:
        room.section_key = section_key
        updates.append("section_key")
    if room.title != title:
        room.title = title
        updates.append("title")
    if not room.is_active:
        room.is_active = True
        updates.append("is_active")
    if updates:
        room.save(update_fields=updates)
    if created:
        seed_staff_members(room)
    return room


def ensure_section_rooms() -> list[ChatRoom]:
    """Crée les 4 salons pupitre s’ils n’existent pas."""
    return [ensure_section_room(key) for key, _title, _postes in SECTION_ROOM_DEFS]


def musician_section_keys(user) -> set[str]:
    """
    Clés de salons pupitre pour un musicien.
    Basé sur poste titulaire + postes remplaçant ; le chant est dans tous.
    """
    if not getattr(user, "is_musician", False) or not user.is_active:
        return set()
    from django.core.exceptions import ObjectDoesNotExist

    try:
        profile = user.musician_profile
    except ObjectDoesNotExist:
        return set()
    postes: set[str] = set()
    if profile.poste_titulaire:
        postes.add(profile.poste_titulaire)
    postes.update(profile.postes_remplacant)
    if not postes:
        return set()
    if CHANT_POSTE in postes:
        return {key for key, _title, _postes in SECTION_ROOM_DEFS}
    keys: set[str] = set()
    for key, _title, room_postes in SECTION_ROOM_DEFS:
        if postes & room_postes:
            keys.add(key)
    return keys


def sync_musician_to_section_rooms(user) -> int:
    """
    Aligne les memberships pupitre d’un musicien (ajoute / réintègre / soft-leave).
    Retourne le nombre de salons où le membre est actif après sync.
    """
    ensure_section_rooms()
    wanted = musician_section_keys(user)
    rooms = list(
        ChatRoom.objects.filter(
            kind=ChatRoom.Kind.SECTION,
            section_key__in=[k for k, _, _ in SECTION_ROOM_DEFS],
        )
    )
    active_n = 0
    subscribed = bool(getattr(user, "chat_auto_subscribe", True))
    for room in rooms:
        if room.section_key in wanted:
            membership, created = ChatMembership.objects.get_or_create(
                room=room,
                user=user,
                defaults={"subscribed": subscribed},
            )
            if not created and membership.left_at is not None:
                membership.rejoin(subscribed=subscribed)
            active_n += 1
        else:
            membership = ChatMembership.objects.filter(room=room, user=user).first()
            if membership is not None and membership.left_at is None:
                membership.leave()
    return active_n


def sync_all_musicians_to_section_rooms() -> tuple[int, int]:
    """Backfill : assure les salons + sync tous les musiciens actifs."""
    rooms = ensure_section_rooms()
    n_users = 0
    for user in User.objects.filter(is_musician=True, is_active=True).select_related(
        "musician_profile"
    ):
        sync_musician_to_section_rooms(user)
        n_users += 1
    return len(rooms), n_users


def sync_participation_to_chat(participation) -> ChatMembership:
    event = participation.event
    if getattr(event, "is_rehearsal", False):
        room = ensure_rehearsals_room()
        membership = add_member(room, participation.user)
        tip_id = _rehearsal_setlist_tip_id(room)
        if tip_id and membership.last_digested_message_id < tip_id:
            membership.last_digested_message_id = tip_id
            membership.save(update_fields=["last_digested_message_id"])
        return membership

    room = ensure_event_room(event)
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
    # Parent soft-deleted : pas de trace (« Message supprimé ») — preview neutre.
    if parent.is_deleted:
        preview = "…"
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


def chat_messages_related(qs):
    """select_related / prefetch partagés pour sérialiser un fil."""
    return qs.select_related(
        "author",
        "related_proposal",
        "reply_to",
        "reply_to__author",
        "thread_event",
    ).prefetch_related(
        "attachments",
        "reactions",
        "reply_to__attachments",
        replies_prefetch(),
    )


def orchestra_archived_q(user_id: int, last_read_at, *, now=None) -> Q:
    """
    Messages du salon Orchestre à archiver *pour cet utilisateur*.

    Un message est archivé s’il a plus d’un mois (activité : édition ou envoi)
    **et** que la personne l’a déjà lu (watermark ``last_read_at``, ou auteur).
    Les non-lus restent dans le fil courant, même s’ils sont vieux.
    """
    now = now or timezone.now()
    cutoff = now - ORCHESTRA_ARCHIVE_AFTER
    old = Q(edited_at__lt=cutoff) | (
        Q(edited_at__isnull=True) & Q(created_at__lt=cutoff)
    )
    if last_read_at is None:
        return old & Q(author_id=user_id)
    read = Q(author_id=user_id) | (
        Q(edited_at__isnull=False, edited_at__lte=last_read_at)
        | Q(edited_at__isnull=True, created_at__lte=last_read_at)
    )
    return old & read


def list_orchestra_archive(
    room: ChatRoom,
    user,
    *,
    last_read_at=None,
    before_id=None,
    include_id=None,
    limit: int = CHAT_ARCHIVE_PAGE,
    viewer=None,
) -> dict:
    """
    Page de messages archivés (salon Orchestre), ordre chronologique.

    ``before_id`` : charger plus ancien que ce message.
    ``include_id`` : fenêtre autour d’un message (lien ?msg=).
    """
    empty = {
        "messages": [],
        "has_more": False,
        "next_before": None,
        "found": False,
    }
    if room.kind != ChatRoom.Kind.ORCHESTRA:
        return empty
    viewer = viewer or user
    try:
        limit = int(limit or CHAT_ARCHIVE_PAGE)
    except (TypeError, ValueError):
        limit = CHAT_ARCHIVE_PAGE
    limit = max(1, min(limit, 100))

    qs = ChatMessage.objects.filter(room=room, deleted_at__isnull=True).filter(
        orchestra_archived_q(user.pk, last_read_at)
    )

    try:
        include_id = int(include_id) if include_id else None
    except (TypeError, ValueError):
        include_id = None
    try:
        before_id = int(before_id) if before_id else None
    except (TypeError, ValueError):
        before_id = None

    if include_id and not before_id:
        target = qs.filter(pk=include_id).first()
        if target is None:
            return {**empty, "has_more": qs.exists()}
        older = list(
            reversed(
                list(
                    chat_messages_related(
                        qs.filter(created_at__lt=target.created_at)
                    ).order_by("-created_at")[:CHAT_ARCHIVE_AROUND]
                )
            )
        )
        newer = list(
            chat_messages_related(
                qs.filter(created_at__gt=target.created_at)
            ).order_by("created_at")[:CHAT_ARCHIVE_AROUND]
        )
        target = chat_messages_related(qs.filter(pk=target.pk)).get()
        history = older + [target] + newer
        oldest = history[0]
        has_more = qs.filter(created_at__lt=oldest.created_at).exists()
        return {
            "messages": [serialize_message(m, viewer=viewer) for m in history],
            "has_more": has_more,
            "next_before": oldest.pk,
            "found": True,
        }

    page_qs = qs.order_by("-created_at")
    if before_id:
        before_created = (
            ChatMessage.objects.filter(pk=before_id, room=room)
            .values_list("created_at", flat=True)
            .first()
        )
        if before_created is not None:
            page_qs = page_qs.filter(created_at__lt=before_created)
    rows = list(chat_messages_related(page_qs)[: limit + 1])
    has_more = len(rows) > limit
    rows = rows[:limit]
    history = list(reversed(rows))
    return {
        "messages": [serialize_message(m, viewer=viewer) for m in history],
        "has_more": has_more,
        "next_before": history[0].pk if history else None,
        "found": True,
    }


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
        "thread_event_id": message.thread_event_id,
        "attachments": (
            []
            if message.is_deleted
            else [serialize_attachment(a) for a in message.attachments.all()]
        ),
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


def unread_counts_for_memberships(memberships) -> dict[int, int]:
    """Compte les non-lus de plusieurs memberships en une seule requête."""
    membership_ids = [m.pk for m in memberships if getattr(m, "pk", None)]
    if not membership_ids:
        return {}

    return dict(
        ChatMembership.objects.filter(pk__in=membership_ids)
        .annotate(
            unread=Count(
                "room__messages",
                filter=unread_messages_filter(),
                distinct=True,
            )
        )
        .values_list("pk", "unread")
    )


def piece_chat_stats_for_user(piece_ids: list[int], user) -> dict[int, dict]:
    """
    Compteurs salon par morceau : ``room_id``, ``unread``, ``total``.
    Les morceaux sans salon sont omis. Tolère l’absence des tables chat.
    """
    if not piece_ids or user is None or not getattr(user, "is_authenticated", False):
        return {}
    from django.db import OperationalError, ProgrammingError

    try:
        rooms = list(
            ChatRoom.objects.filter(
                piece_id__in=piece_ids,
                kind=ChatRoom.Kind.PIECE,
                is_active=True,
            ).annotate(
                msg_total=Count(
                    "messages",
                    filter=Q(messages__deleted_at__isnull=True),
                )
            )
        )
    except (ProgrammingError, OperationalError):
        logger.warning("piece_chat_stats_for_user indisponible (migration ?)")
        return {}

    if not rooms:
        return {}

    unread_by_room: dict[int, int] = {}
    try:
        memberships = list(
            ChatMembership.objects.filter(
                user=user,
                left_at__isnull=True,
                room_id__in=[r.pk for r in rooms],
            )
        )
        unread_by_mid = unread_counts_for_memberships(memberships)
        unread_by_room = {m.room_id: unread_by_mid.get(m.pk, 0) for m in memberships}
    except (ProgrammingError, OperationalError):
        logger.warning("piece_chat_stats_for_user unread indisponible (migration ?)")

    return {
        room.piece_id: {
            "room_id": room.pk,
            "unread": unread_by_room.get(room.pk, 0),
            "total": int(room.msg_total or 0),
        }
        for room in rooms
        if room.piece_id is not None
    }


def attach_piece_chat_stats(pieces, user) -> None:
    """Pose ``piece.chat_stats`` (room_id / unread / total) sur chaque morceau."""
    ids = [p.pk for p in pieces]
    stats = piece_chat_stats_for_user(ids, user)
    for piece in pieces:
        piece.chat_stats = stats.get(
            piece.pk, {"room_id": None, "unread": 0, "total": 0}
        )


def _last_name_letters(last_name: str) -> str:
    """Lettres du nom (sans espaces / tirets) pour désambiguïser les @Prénom."""
    return "".join(c for c in (last_name or "") if c.isalpha())


def assign_mention_handles(users: list) -> dict[int, str]:
    """
    Handle visible pour @mention : prénom seul ; si homonymes dans la liste,
    « Prénom » + préfixe progressif des lettres du nom jusqu’à unicité
    (ex. Stéphane G / Stéphane P).
    """
    from collections import defaultdict

    groups: dict[str, list] = defaultdict(list)
    first_by_id: dict[int, str] = {}
    for u in users:
        first = (getattr(u, "first_name", "") or "").strip() or (
            getattr(u, "username", "") or ""
        ).strip()
        first_by_id[u.pk] = first
        groups[first.casefold()].append(u)

    handles: dict[int, str] = {}
    for group in groups.values():
        if len(group) == 1:
            u = group[0]
            handles[u.pk] = first_by_id[u.pk]
            continue

        letters_by_id = {
            u.pk: _last_name_letters(getattr(u, "last_name", "") or "")
            for u in group
        }
        max_len = max((len(s) for s in letters_by_id.values()), default=0)
        n = 1
        while n <= max_len:
            prefixes = [letters_by_id[u.pk][:n] for u in group]
            if all(prefixes) and len({p.casefold() for p in prefixes}) == len(group):
                break
            n += 1

        used: dict[str, int] = {}
        for u in group:
            first = first_by_id[u.pk]
            letters = letters_by_id[u.pk]
            if letters and n <= max_len:
                handle = f"{first} {letters[:n]}"
            elif letters:
                handle = f"{first} {letters}"
            else:
                handle = first
            key = handle.casefold()
            if key in used:
                # Homonymes complets → repli username
                handle = (getattr(u, "username", "") or "").strip() or handle
                key = handle.casefold()
            used[key] = u.pk
            handles[u.pk] = handle
    return handles


def serialize_mention_member(user, *, handle: str | None = None) -> dict:
    name = (user.get_full_name() or "").strip() or user.username
    if handle is None:
        handle = assign_mention_handles([user]).get(user.pk) or (
            (user.first_name or "").strip() or user.username
        )
    return {
        "id": user.pk,
        "username": user.username,
        "name": name,
        "handle": handle,
    }


def serialize_mention_members(users: list) -> list:
    handles = assign_mention_handles(users)
    return [serialize_mention_member(u, handle=handles[u.pk]) for u in users]


def room_mention_members(room: ChatRoom) -> list:
    """
    Candidats @mention pour l’autocomplete.
    Salons généraux : musiciens actifs (+ membres du salon).
    Salon Staff : uniquement comptes staff (pas tout l’orchestre).
    """
    User = get_user_model()
    if room.kind == ChatRoom.Kind.STAFF:
        q = Q(is_staff=True) | Q(is_superuser=True)
    elif room.kind == ChatRoom.Kind.SECTION:
        # Pupitre : uniquement les membres actifs (pas tout l’orchestre).
        q = Q(
            chat_memberships__room=room,
            chat_memberships__left_at__isnull=True,
        )
    else:
        q = Q(is_musician=True) | Q(
            chat_memberships__room=room,
            chat_memberships__left_at__isnull=True,
        )
    qs = User.objects.filter(is_active=True).filter(q).distinct()
    return list(qs.order_by("last_name", "first_name", "username")[:300])


def _mention_tokens_for_users(users: list) -> list[str]:
    handles = assign_mention_handles(users)
    tokens: list[str] = []
    for u in users:
        if getattr(u, "username", None):
            tokens.append(u.username)
        h = handles.get(u.pk)
        if h:
            tokens.append(h)
    return tokens


def _mention_alternation_re(tokens: list[str]):
    cleaned = sorted({t for t in tokens if t}, key=len, reverse=True)
    if not cleaned:
        return None
    return re.compile(
        r"(?<![\w.])@(" + "|".join(re.escape(t) for t in cleaned) + r")(?![\w.-])",
        re.UNICODE | re.IGNORECASE,
    )


def extract_mention_tokens(body: str, *, known_tokens: list[str] | None = None) -> list[str]:
    if not body:
        return []
    found: list[str] = []
    spans: list[tuple[int, int]] = []
    if known_tokens:
        pat = _mention_alternation_re(known_tokens)
        if pat is not None:
            for m in pat.finditer(body):
                found.append(m.group(1))
                spans.append(m.span())
    for m in MENTION_TOKEN_RE.finditer(body):
        start, end = m.span()
        if any(start < e and end > s for s, e in spans):
            continue
        found.append(m.group(1))
        spans.append((start, end))
    return found


def resolve_mentioned_users(room: ChatRoom, body: str, *, exclude_user=None) -> list:
    """
    Résout les @handle / @username vers des utilisateurs mentionnables.
    Si la personne n’est pas encore membre du salon, elle y est ajoutée
    (pour pouvoir ouvrir le lien de la notification).
    """
    candidates = room_mention_members(room)
    known = _mention_tokens_for_users(candidates)
    raw_tokens = extract_mention_tokens(body, known_tokens=known)
    tokens = {t.casefold() for t in raw_tokens}
    if not tokens:
        return []
    handles = assign_mention_handles(candidates)
    exclude_id = getattr(exclude_user, "pk", None)
    matched = []
    seen: set[int] = set()
    for u in candidates:
        uname = (u.username or "").casefold()
        handle = (handles.get(u.pk) or "").casefold()
        if uname not in tokens and handle not in tokens:
            continue
        if exclude_id and u.pk == exclude_id:
            continue
        if u.pk in seen:
            continue
        seen.add(u.pk)
        if room.kind == ChatRoom.Kind.STAFF and not (u.is_staff or u.is_superuser):
            continue
        if not user_can_access_room(u, room):
            # Événement / morceau : ajouter pour que la notif soit ouvrable.
            # Pupitre : pas d’ajout auto (composition figée par poste).
            if room.kind == ChatRoom.Kind.SECTION:
                continue
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
    """
    True si l’utilisateur est couvert par une notif dédiée (mention / réponse)
    et ne doit pas être compté dans le digest « chatter » du salon.
    """
    if message.author_id == user_id:
        return False
    if (
        message.reply_to_id
        and message.reply_to
        and message.reply_to.author_id == user_id
    ):
        return True
    room = message.room
    candidates = room_mention_members(room) if room is not None else []
    known = _mention_tokens_for_users(candidates)
    tokens = {t.casefold() for t in extract_mention_tokens(message.body or "", known_tokens=known)}
    if not tokens:
        return False
    user_tokens: set[str] = set()
    uname = (username or "").strip()
    if not uname:
        User = get_user_model()
        try:
            uname = User.objects.only("username").get(pk=user_id).username
        except User.DoesNotExist:
            uname = ""
    if uname:
        user_tokens.add(uname.casefold())
    handles = assign_mention_handles(candidates)
    handle = handles.get(user_id)
    if handle:
        user_tokens.add(handle.casefold())
    return bool(user_tokens & tokens)


def _chat_notify_preview(message: ChatMessage) -> str:
    preview = (message.body or "").strip()
    if not preview:
        preview = "pièce jointe"
    if len(preview) > 140:
        preview = preview[:137].rstrip() + "…"
    return preview


def notify_chat_message_targets(
    message: ChatMessage,
    *,
    previous_body: str | None = None,
    notify_reply: bool = True,
) -> int:
    """
    Notifie les @mentions (toujours immédiat) et l’auteur du message cité
    (selon la préf. « réponses à mes messages »).

    Une @mention produit une alerte dédiée (« vous interpelle ») et retire
    ce message du digest salon pour le destinataire — pas de 2ᵉ notif
    « nouveau message » pour le même contenu. Mention + réponse → une seule
    notif (la mention). L’auteur du message n’est jamais notifié. Ne lève jamais.

    ``previous_body`` : lors d’une édition, seuls les *nouveaux* @ sont notifiés.
    """
    if message.kind == ChatMessage.Kind.SYSTEM:
        return 0
    if message.is_deleted:
        return 0

    mention_recipients: dict[int, object] = {}
    for u in resolve_mentioned_users(
        message.room,
        message.body or "",
        exclude_user=message.author,
    ):
        mention_recipients[u.pk] = u

    if previous_body is not None:
        already_mentioned = {
            u.pk
            for u in resolve_mentioned_users(
                message.room,
                previous_body or "",
                exclude_user=message.author,
            )
        }
        for uid in list(mention_recipients):
            if uid in already_mentioned:
                mention_recipients.pop(uid, None)

    # Déjà notifié pour ce message (édition / retry) → pas de doublon inbox.
    if mention_recipients:
        try:
            from users.models import UserNotification

            already_notified = set(
                UserNotification.objects.filter(
                    user_id__in=list(mention_recipients.keys()),
                    related_id=message.pk,
                    related_type__in=("chat_mention", "chat_msg"),
                ).values_list("user_id", flat=True)
            )
            for uid in already_notified:
                mention_recipients.pop(uid, None)
        except Exception:
            logger.exception(
                "Filtre anti-doublon mention indisponible message_id=%s",
                message.pk,
            )

    reply_recipients: dict[int, object] = {}
    parent = message.reply_to
    if (
        notify_reply
        and parent
        and parent.author_id
        and parent.author_id != message.author_id
        and parent.author is not None
        and parent.author.is_active
    ):
        reply_recipients[parent.author_id] = parent.author

    # Filet : jamais notifier l’auteur ; pas de double notif mention+réponse
    if message.author_id:
        mention_recipients.pop(message.author_id, None)
        reply_recipients.pop(message.author_id, None)
    for uid in mention_recipients:
        reply_recipients.pop(uid, None)

    if not mention_recipients and not reply_recipients:
        return 0

    author_name = _author_display_name(message)
    room_title = message.room.title
    preview = _chat_notify_preview(message)
    url = chat_room_url(
        message.room_id,
        message_id=message.pk,
        thread_event_id=message.thread_event_id,
    )
    title = f"JOY — {room_title}"
    sent = 0

    try:
        from users.notify import notify_users
        from users.notify_prefs import TYPE_CHAT, TYPE_CHAT_REPLY

        if mention_recipients:
            sent += notify_users(
                mention_recipients.values(),
                title=title,
                body=f"{author_name} vous interpelle dans {room_title} : {preview}",
                url=url,
                related_type="chat_mention",
                related_id=message.pk,
                notify_type=TYPE_CHAT,
                room=message.room,
                force_immediate=True,
            )
        if reply_recipients:
            sent += notify_users(
                reply_recipients.values(),
                title=title,
                body=(
                    f"{author_name} a répondu à votre message "
                    f"dans {room_title} : {preview}"
                ),
                url=url,
                related_type="chat_reply",
                related_id=message.pk,
                notify_type=TYPE_CHAT_REPLY,
                room=message.room,
                force_immediate=False,
            )
        return sent
    except Exception:
        logger.exception(
            "Échec notif mention/réponse chat message_id=%s", message.pk
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
    thread_event=None,
    thread_event_id=None,
    require_thread: bool | None = None,
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

    # Hérite du fil du message parent si réponse.
    if reply_to is not None and reply_to.thread_event_id and thread_event is None:
        thread_event = reply_to.thread_event
        thread_event_id = reply_to.thread_event_id

    if thread_event is None and thread_event_id is not None:
        thread_event = resolve_rehearsal_thread_event(room, thread_event_id)
        if thread_event is None and room.kind == ChatRoom.Kind.REHEARSALS:
            raise ValueError("Fil de répétition invalide.")
    elif thread_event is not None:
        if room.kind == ChatRoom.Kind.REHEARSALS and not getattr(
            thread_event, "is_rehearsal", False
        ):
            raise ValueError("Fil de répétition invalide.")
        if room.kind != ChatRoom.Kind.REHEARSALS:
            thread_event = None

    if require_thread is None:
        require_thread = (
            room.kind == ChatRoom.Kind.REHEARSALS and kind == ChatMessage.Kind.NORMAL
        )
    if require_thread and thread_event is None:
        raise ValueError("Choisissez une date de répétition pour publier.")

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
        thread_event=thread_event,
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
            "author",
            "related_proposal",
            "reply_to",
            "reply_to__author",
            "thread_event",
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

    previous_body = message.body or ""
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
    # Nouveaux @ seulement ; pas de 2ᵉ notif « réponse » à chaque édition.
    notify_chat_message_targets(
        message,
        previous_body=previous_body,
        notify_reply=False,
    )
    return message


@transaction.atomic
def delete_message(*, message: ChatMessage, actor) -> ChatMessage:
    """
    Soft-delete d’un message (auteur uniquement). La ligne reste en base pour
    les FK reply_to, mais le message disparaît du fil (pas de placeholder).
    """
    if message.is_deleted:
        raise ValueError("Message déjà supprimé.")
    if message.kind != ChatMessage.Kind.NORMAL:
        raise ValueError("Ce message ne peut pas être supprimé.")
    if message.author_id != getattr(actor, "pk", None):
        raise ValueError("Seul l’auteur peut supprimer ce message.")

    message.deleted_at = timezone.now()
    message.save(update_fields=["deleted_at"])

    message = (
        ChatMessage.objects.select_related(
            "author", "related_proposal", "reply_to", "reply_to__author"
        )
        .prefetch_related("attachments", "reactions", "reply_to__attachments")
        .get(pk=message.pk)
    )
    broadcast_message_edit(message)
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


def build_room_embed_context(
    request: HttpRequest,
    room: ChatRoom,
    *,
    compact: bool = False,
    show_staff_panel: bool = True,
    history_limit: int | None = None,
    thread_event_id=None,
) -> dict:
    """
    Contexte partagé salon chat (page dédiée ou embed poll / calendrier).
    Prérequis : l'utilisateur a déjà accès (membre actif ou staff).

    Salon Répétitions :
    - sans ``thread_event_id`` → liste des fils (pas de composer)
    - avec ``thread_event_id`` → messages du fil + composer
    """
    user = request.user
    is_staff = user.is_staff or user.is_superuser
    membership = active_membership(room, user)
    if membership is None and is_staff:
        membership = ensure_staff_membership(room, user)

    is_rehearsal_room = room.kind == ChatRoom.Kind.REHEARSALS or bool(
        room.event_id and getattr(getattr(room, "event", None), "is_rehearsal", False)
    )
    if room.kind == ChatRoom.Kind.REHEARSALS:
        ensure_rehearsal_setlist_tip(room)

    if thread_event_id is None and hasattr(request, "GET"):
        thread_event_id = request.GET.get("thread")

    active_thread_event = None
    rehearsal_threads: list[dict] = []
    rehearsal_threads_archived: list[dict] = []
    threads_mode = False
    if room.kind == ChatRoom.Kind.REHEARSALS:
        active_thread_event = resolve_rehearsal_thread_event(room, thread_event_id)
        if active_thread_event is None:
            threads_mode = True
            rehearsal_threads, rehearsal_threads_archived = partition_rehearsal_threads(
                room, user
            )

    # Curseur avant mark_room_read : 1er non-lu + archive Orchestre (par personne).
    initial_last_read_dt = (
        membership.last_read_at if membership and membership.last_read_at else None
    )
    initial_last_read_at = (
        initial_last_read_dt.isoformat() if initial_last_read_dt else None
    )
    # Liste des fils : ne pas marquer tout le salon lu (sinon badges fil inutiles).
    if not threads_mode:
        mark_room_read(room, user, broadcast=True)

    limit = history_limit if history_limit is not None else CHAT_HISTORY_LIMIT
    if compact and history_limit is None:
        limit = min(CHAT_HISTORY_LIMIT, 40)

    archive_enabled = (
        room.kind == ChatRoom.Kind.ORCHESTRA and not compact and not threads_mode
    )
    archive_count = 0
    archive_focus_id = None
    api_archive_url = ""

    if threads_mode:
        history = []
    else:
        if active_thread_event is not None:
            ensure_rehearsal_thread_opener(active_thread_event)
        msg_qs = ChatMessage.objects.filter(room=room, deleted_at__isnull=True)
        if active_thread_event is not None:
            msg_qs = msg_qs.filter(thread_event_id=active_thread_event.pk)
        if archive_enabled:
            archived_q = orchestra_archived_q(user.pk, initial_last_read_dt)
            archive_count = msg_qs.filter(archived_q).count()
            msg_qs = msg_qs.filter(~archived_q)
            api_archive_url = reverse(
                "chat:api_archive", kwargs={"room_id": room.pk}
            )
            if hasattr(request, "GET"):
                try:
                    focus = int(request.GET.get("msg") or 0)
                except (TypeError, ValueError):
                    focus = 0
                if focus and ChatMessage.objects.filter(
                    pk=focus,
                    room=room,
                    deleted_at__isnull=True,
                ).filter(archived_q).exists():
                    archive_focus_id = focus
        history = list(
            reversed(
                list(
                    chat_messages_related(msg_qs).order_by("-created_at")[:limit]
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
        if is_staff and show_staff_panel:
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

    active_thread = None
    if active_thread_event is not None:
        active_thread = serialize_rehearsal_thread(
            active_thread_event,
            room=room,
            user=user,
            last_read_at=membership.last_read_at if membership else None,
        )

    ws_scheme = "wss" if request.is_secure() else "ws"
    ws_url = f"{ws_scheme}://{request.get_host()}/ws/chat/{room.pk}/"
    api_send_url = reverse("chat:api_send", kwargs={"room_id": room.pk})
    api_react_url = reverse("chat:api_react", kwargs={"room_id": room.pk})
    api_edit_url = reverse("chat:api_edit", kwargs={"room_id": room.pk})
    api_delete_url = reverse("chat:api_delete", kwargs={"room_id": room.pk})
    # ?v=3 : Staff = staff only (no full orchestra in @ mentions)
    api_members_url = (
        reverse("chat:api_members", kwargs={"room_id": room.pk}) + "?v=4"
    )
    messages_data = [serialize_message(m, viewer=user) for m in history]
    mention_members = serialize_mention_members(room_mention_members(room))
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
        "api_delete_url": api_delete_url,
        "api_members_url": api_members_url,
        "api_read_url": reverse("chat:api_read", kwargs={"room_id": room.pk}),
        "api_archive_url": api_archive_url,
        "archive_enabled": archive_enabled,
        "archive_count": archive_count,
        "archive_focus_id": archive_focus_id,
        "current_user_id": user.pk,
        "initial_last_read_at": initial_last_read_at,
        "is_planning_staff": is_staff,
        "draft_proposal": draft_proposal,
        "invite_musicians": invite_musicians,
        "invite_choices": invite_choices,
        "open_proposal": open_proposal,
        "lock_options": lock_options,
        "is_rehearsal_room": is_rehearsal_room,
        "threads_mode": threads_mode,
        "rehearsal_threads": rehearsal_threads,
        "rehearsal_threads_archived": rehearsal_threads_archived,
        "active_thread": active_thread,
        "active_thread_event_id": (
            active_thread_event.pk if active_thread_event else None
        ),
        "composer_placeholder": (
            "Proposez un morceau… (votez avec 👍)"
            if is_rehearsal_room
            else "Message… — @ pour mentionner"
        ),
        "embedded": True,
        "compact": bool(compact),
        "show_chat_chrome": False,
        "show_staff_panel": bool(show_staff_panel) and is_staff and bool(room.event_id),
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
