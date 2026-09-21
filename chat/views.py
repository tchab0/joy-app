from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import (
    FileResponse,
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from chat.models import ChatAttachment, ChatMembership, ChatMessage, ChatRoom
from chat.services import (
    active_membership,
    add_member,
    build_room_embed_context,
    create_thematic_room,
    deactivate_rehearsal_event_rooms,
    delete_message,
    edit_message,
    ensure_staff_membership,
    ensure_staff_room,
    is_thematic_room,
    join_thematic_room,
    list_discoverable_thematic_rooms,
    list_orchestra_archive,
    mark_room_read,
    post_message,
    remove_thematic_member,
    room_mention_members,
    serialize_mention_members,
    serialize_message,
    sync_user_to_staff_room,
    toggle_reaction,
    unread_messages_filter,
    user_can_access_room,
)
from users.forms import NotificationPrefsForm
from users.roles import user_can_access_planning


def _require_musician(request: HttpRequest) -> HttpResponse | None:
    if not request.user.is_authenticated:
        return redirect("account_login")
    if not user_can_access_planning(request.user):
        return HttpResponseForbidden("Accès réservé aux musiciens.")
    return None


def _require_staff(request: HttpRequest) -> HttpResponse | None:
    denied = _require_musician(request)
    if denied:
        return denied
    if not (request.user.is_staff or request.user.is_superuser):
        return HttpResponseForbidden("Accès réservé au staff.")
    return None


@login_required
@require_GET
def room_list(request: HttpRequest) -> HttpResponse:
    denied = _require_musician(request)
    if denied:
        return denied

    if request.user.is_staff or request.user.is_superuser:
        sync_user_to_staff_room(request.user)

    # Anciens salons EVENT liés à une répétition → hors liste « Événements ».
    deactivate_rehearsal_event_rooms()

    list_view = (request.GET.get("vue") or "mes").strip().lower()
    if list_view not in {"mes", "tous"}:
        list_view = "mes"

    from django.db.models import Count, OuterRef, Subquery

    last_msg = ChatMessage.objects.filter(
        room_id=OuterRef("room_id"), deleted_at__isnull=True
    ).order_by("-created_at")
    memberships = list(
        ChatMembership.objects.filter(
            user=request.user,
            left_at__isnull=True,
            room__is_active=True,
        )
        .select_related("room", "room__event", "room__event__type", "room__piece")
        .annotate(
            last_msg_id=Subquery(last_msg.values("pk")[:1]),
            unread=Count(
                "room__messages",
                filter=unread_messages_filter(),
                distinct=True,
            ),
        )
        .order_by("-room__created_at")
    )
    last_ids = [m.last_msg_id for m in memberships if m.last_msg_id]
    last_by_id = {
        msg.pk: msg
        for msg in ChatMessage.objects.filter(pk__in=last_ids).select_related("author")
    }

    def _sort_key(item: dict):
        """Plus récent message en premier ; salons à rejoindre en bas."""
        last = item["last_message"]
        last_ts = last.created_at.timestamp() if last else 0.0
        join_rank = 1 if item.get("can_join") else 0
        return (
            join_rank,
            -last_ts,
            -item["room"].created_at.timestamp(),
        )

    primary_rooms: list[dict] = []
    piece_rooms: list[dict] = []
    event_rooms: list[dict] = []
    for m in memberships:
        item = {
            "membership": m,
            "room": m.room,
            "unread": m.unread,
            "last_message": last_by_id.get(m.last_msg_id),
            "can_join": False,
        }
        kind = m.room.kind
        if kind == ChatRoom.Kind.PIECE:
            piece_rooms.append(item)
        elif kind == ChatRoom.Kind.EVENT and m.room.event_id:
            event = m.room.event
            # Les répétitions ont le salon dédié « Répétitions ».
            if event is not None and getattr(event, "is_rehearsal", False):
                continue
            event_rooms.append(item)
        else:
            # Thématiques + privés ad hoc (sans Event) → liste principale
            primary_rooms.append(item)

    if list_view == "tous":
        for room in list_discoverable_thematic_rooms(request.user):
            primary_rooms.append(
                {
                    "membership": None,
                    "room": room,
                    "unread": 0,
                    "last_message": None,
                    "can_join": True,
                }
            )

    primary_rooms.sort(key=_sort_key)
    piece_rooms.sort(key=_sort_key)
    event_rooms.sort(key=_sort_key)

    piece_unread_total = sum(i["unread"] for i in piece_rooms)
    event_unread_total = sum(i["unread"] for i in event_rooms)

    return render(
        request,
        "chat/room_list.html",
        {
            "list_view": list_view,
            "primary_rooms": primary_rooms,
            "piece_rooms": piece_rooms,
            "event_rooms": event_rooms,
            "piece_has_unread": piece_unread_total > 0,
            "event_has_unread": event_unread_total > 0,
            "piece_unread_total": piece_unread_total,
            "event_unread_total": event_unread_total,
            "has_rooms": bool(primary_rooms or piece_rooms or event_rooms),
            "is_planning_staff": bool(
                request.user.is_staff or request.user.is_superuser
            ),
        },
    )




@login_required
@require_GET
def staff_room(request: HttpRequest) -> HttpResponse:
    """Raccourci Coulisses → salon Staff (staff uniquement)."""
    denied = _require_staff(request)
    if denied:
        return denied
    room = ensure_staff_room()
    sync_user_to_staff_room(request.user)
    return redirect("chat:room", room_id=room.pk)


@login_required
@require_http_methods(["GET", "POST"])
def thematic_create(request: HttpRequest) -> HttpResponse:
    """Staff : créer un salon thématique et y ajouter des musiciens."""
    denied = _require_staff(request)
    if denied:
        return denied

    User = get_user_model()
    musicians = list(
        User.objects.filter(is_musician=True, is_active=True).order_by(
            "last_name", "first_name", "username"
        )[:300]
    )

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        raw_ids = request.POST.getlist("musician_ids")
        selected_ids: set[int] = set()
        for raw in raw_ids:
            try:
                selected_ids.add(int(raw))
            except (TypeError, ValueError):
                continue
        selected = [m for m in musicians if m.pk in selected_ids]
        try:
            room = create_thematic_room(
                title,
                musician_users=selected,
                created_by=request.user,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                "chat/thematic_create.html",
                {
                    "musicians": musicians,
                    "title_value": title,
                    "selected_ids": selected_ids,
                    "is_planning_staff": True,
                },
            )
        messages.success(request, f"Salon « {room.title} » créé.")
        return redirect("chat:room", room_id=room.pk)

    return render(
        request,
        "chat/thematic_create.html",
        {
            "musicians": musicians,
            "title_value": "",
            "selected_ids": set(),
            "is_planning_staff": True,
        },
    )


@login_required
@require_POST
def thematic_join(request: HttpRequest, room_id: int) -> HttpResponse:
    """Musicien : devenir membre d’un salon thématique (vue Tous les salons)."""
    denied = _require_musician(request)
    if denied:
        return denied

    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    try:
        join_thematic_room(room, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(f"{reverse('chat:list')}?vue=tous")

    messages.success(request, f"Vous êtes membre de « {room.title} ».")
    return redirect("chat:room", room_id=room.pk)


@login_required
@require_POST
def thematic_member_add(request: HttpRequest, room_id: int) -> HttpResponse:
    """Staff : ajouter un musicien à un salon thématique."""
    denied = _require_staff(request)
    if denied:
        return denied

    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    if not is_thematic_room(room):
        messages.error(request, "Ce salon n’est pas thématique.")
        return redirect("chat:room", room_id=room.pk)

    User = get_user_model()
    try:
        user_id = int(request.POST.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    user = User.objects.filter(
        pk=user_id, is_musician=True, is_active=True
    ).first()
    if user is None:
        messages.error(request, "Musicien invalide.")
        return redirect("chat:room", room_id=room.pk)

    add_member(room, user)
    name = user.get_full_name() or user.username
    messages.success(request, f"{name} a été ajouté au salon.")
    return redirect("chat:room", room_id=room.pk)


@login_required
@require_POST
def thematic_member_remove(request: HttpRequest, room_id: int) -> HttpResponse:
    """Staff : retirer un musicien d’un salon thématique."""
    denied = _require_staff(request)
    if denied:
        return denied

    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    if not is_thematic_room(room):
        messages.error(request, "Ce salon n’est pas thématique.")
        return redirect("chat:room", room_id=room.pk)

    User = get_user_model()
    try:
        user_id = int(request.POST.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        messages.error(request, "Utilisateur invalide.")
        return redirect("chat:room", room_id=room.pk)

    try:
        removed = remove_thematic_member(room, user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("chat:room", room_id=room.pk)

    if removed:
        name = user.get_full_name() or user.username
        messages.success(request, f"{name} a été retiré du salon.")
    else:
        messages.info(request, "Cette personne n’était pas membre du salon.")
    return redirect("chat:room", room_id=room.pk)





@login_required
@require_http_methods(["GET", "POST"])
def room_detail(request: HttpRequest, room_id: int) -> HttpResponse:
    denied = _require_musician(request)
    if denied:
        return denied

    room = get_object_or_404(
        ChatRoom.objects.select_related(
            "event",
            "event__venue",
            "event__type",
            "event__parent",
            "piece",
        ),
        pk=room_id,
        is_active=True,
    )
    membership = active_membership(room, request.user)
    is_staff = request.user.is_staff or request.user.is_superuser
    if room.kind == ChatRoom.Kind.STAFF and not is_staff:
        return HttpResponseForbidden("Salon réservé au staff.")
    if membership is None and not is_staff:
        # Peut avoir quitté : afficher page de réintégration si membership existe
        try:
            left = ChatMembership.objects.get(room=room, user=request.user)
        except ChatMembership.DoesNotExist:
            return HttpResponseForbidden("Vous n’êtes pas membre de ce salon.")
        return render(
            request,
            "chat/room_left.html",
            {"room": room, "membership": left},
        )

    if membership is None and is_staff:
        membership = ensure_staff_membership(room, request.user)

    from users.notify import mark_chat_room_notifications_read

    mark_chat_room_notifications_read(request.user, room.pk)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "subscribe":
            membership.subscribed = True
            membership.save(update_fields=["subscribed"])
            messages.success(request, "Notifications activées pour ce salon.")
            return redirect("chat:room", room_id=room.pk)
        if action == "unsubscribe":
            membership.subscribed = False
            membership.save(update_fields=["subscribed"])
            messages.success(request, "Notifications désactivées pour ce salon.")
            return redirect("chat:room", room_id=room.pk)
        if action == "leave":
            if room.kind in {
                ChatRoom.Kind.ORCHESTRA,
                ChatRoom.Kind.STAFF,
                ChatRoom.Kind.SECTION,
            }:
                messages.error(request, "Ce salon ne peut pas être quitté.")
                return redirect("chat:room", room_id=room.pk)
            membership.leave()
            messages.info(request, "Vous avez quitté le salon.")
            return redirect("chat:list")
        if action == "send":
            body = request.POST.get("body", "")
            files = request.FILES.getlist("files")
            try:
                post_message(
                    room=room, author=request.user, body=body, files=files
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect("chat:room", room_id=room.pk)

    ctx = build_room_embed_context(request, room)
    ctx["embedded"] = False
    ctx["show_chat_chrome"] = True
    if room.kind == ChatRoom.Kind.STAFF:
        # Teinte slate (joy-staff-page) aussi via /chat/<id>/, pas seulement /chat/staff/
        request.joy_force_staff_surface = True
    return render(request, "chat/room_detail.html", ctx)


@login_required
@require_GET
def room_embed_fragment(request: HttpRequest, room_id: int) -> HttpResponse:
    """Fragment HTML salon compact (calendrier panneau jour)."""
    denied = _require_musician(request)
    if denied:
        return denied

    room = get_object_or_404(
        ChatRoom.objects.select_related(
            "event",
            "event__venue",
            "event__type",
            "event__parent",
            "piece",
        ),
        pk=room_id,
        is_active=True,
    )
    if room.kind == ChatRoom.Kind.STAFF and not (
        request.user.is_staff or request.user.is_superuser
    ):
        return HttpResponseForbidden("Salon réservé au staff.")
    if not user_can_access_room(request.user, room):
        is_staff = request.user.is_staff or request.user.is_superuser
        if not is_staff:
            return HttpResponseForbidden("Vous n’êtes pas membre de ce salon.")

    ctx = build_room_embed_context(
        request,
        room,
        compact=True,
        show_staff_panel=False,
    )
    # IDs uniques si plusieurs embeds potentiels dans la même page.
    suffix = f"cal-{room.pk}"
    ctx["messages_script_id"] = f"chat-messages-{suffix}"
    ctx["mention_members_script_id"] = f"chat-members-{suffix}"
    ctx["read_cursors_script_id"] = f"chat-reads-{suffix}"
    return render(request, "chat/_room_embed.html", ctx)


@login_required
@require_POST
def room_rejoin(request: HttpRequest, room_id: int) -> HttpResponse:
    denied = _require_musician(request)
    if denied:
        return denied
    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    membership = get_object_or_404(ChatMembership, room=room, user=request.user)
    subscribed = bool(getattr(request.user, "chat_auto_subscribe", True))
    membership.rejoin(subscribed=subscribed)
    messages.success(request, "Vous avez rejoint le salon.")
    return redirect("chat:room", room_id=room.pk)


@login_required
@require_http_methods(["GET", "POST"])
def account_prefs(request: HttpRequest) -> HttpResponse:
    if not (
        user_can_access_planning(request.user)
        or request.user.is_staff
        or request.user.is_superuser
    ):
        return HttpResponseForbidden("Accès réservé aux musiciens et au staff.")

    from chat.models import ChatMembership
    from users.notify_prefs import (
        OVERRIDE_DAILY,
        OVERRIDE_FOLLOW,
        OVERRIDE_REALTIME,
        HOUR_CHOICES,
        save_notification_overrides,
        types_for_user,
    )
    from users.models import NotificationTypePref

    form = NotificationPrefsForm(request.POST or None, instance=request.user)
    # Tous les salons encore rejoints (y compris alertes coupées).
    memberships = list(
        ChatMembership.objects.filter(
            user=request.user,
            left_at__isnull=True,
        )
        .select_related("room", "room__event", "room__piece")
        .order_by("room__kind", "room__title")
    )
    try:
        type_prefs = {
            p.notify_type: p
            for p in NotificationTypePref.objects.filter(user=request.user)
        }
    except Exception:
        type_prefs = {}
    type_specs = types_for_user(request.user)

    if request.method == "POST" and form.is_valid():
        form.save()
        errors = save_notification_overrides(
            request.user, request.POST, memberships=memberships
        )
        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            messages.success(request, "Préférences de notifications enregistrées.")
            return redirect("chat:prefs")
        memberships = list(
            ChatMembership.objects.filter(
                user=request.user,
                left_at__isnull=True,
            )
            .select_related("room", "room__event", "room__piece")
            .order_by("room__kind", "room__title")
        )
        try:
            type_prefs = {
                p.notify_type: p
                for p in NotificationTypePref.objects.filter(user=request.user)
            }
        except Exception:
            type_prefs = {}

    type_rows = []
    for spec in type_specs:
        pref = type_prefs.get(spec.key)
        mode = OVERRIDE_FOLLOW
        hour = getattr(request.user, "notify_digest_hour", 18) or 18
        if pref is not None:
            mode = pref.frequency
            if pref.digest_hour is not None:
                hour = pref.digest_hour
        # Dict plat : évite tout souci d’accès dataclass dans le template.
        type_rows.append(
            {
                "key": spec.key,
                "label": spec.label,
                "help_text": spec.help_text,
                "mode": mode,
                "hour": hour,
            }
        )

    room_rows = []
    for m in memberships:
        mode = m.notify_frequency_override or OVERRIDE_FOLLOW
        hour = (
            m.notify_digest_hour
            if m.notify_digest_hour is not None
            else (getattr(request.user, "notify_digest_hour", 18) or 18)
        )
        kind_label = m.room.get_kind_display() if hasattr(m.room, "get_kind_display") else m.room.kind
        room_rows.append(
            {
                "membership": m,
                "mode": mode,
                "hour": hour,
                "subscribed": bool(m.subscribed),
                "kind_label": kind_label,
            }
        )

    return render(
        request,
        "chat/account_prefs.html",
        {
            "form": form,
            "type_rows": type_rows,
            "room_rows": room_rows,
            "hour_choices": HOUR_CHOICES,
            "override_follow": OVERRIDE_FOLLOW,
            "override_realtime": OVERRIDE_REALTIME,
            "override_daily": OVERRIDE_DAILY,
        },
    )


@login_required
@require_POST
def api_send(request: HttpRequest, room_id: int) -> JsonResponse:
    denied = _require_musician(request)
    if denied:
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    if not user_can_access_room(request.user, room):
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    body = request.POST.get("body", "")
    files = request.FILES.getlist("files")
    reply_to_id = request.POST.get("reply_to_id") or None
    try:
        message = post_message(
            room=room,
            author=request.user,
            body=body,
            files=files,
            reply_to_id=reply_to_id,
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse(
        {"ok": True, "message": serialize_message(message, viewer=request.user)}
    )


@login_required
@require_POST
def api_poll(request: HttpRequest, room_id: int) -> JsonResponse:
    """Créer et lancer un sondage depuis le composer d’un salon."""
    denied = _require_musician(request)
    if denied:
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    if not user_can_access_room(request.user, room):
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)
    if active_membership(room, request.user) is None and not (
        request.user.is_staff or request.user.is_superuser
    ):
        return JsonResponse(
            {"ok": False, "error": "Rejoignez le salon pour lancer un sondage."},
            status=403,
        )

    import json

    from django.utils.dateparse import parse_date

    from planning.models import DateProposal
    from planning.services import create_and_launch_chat_poll

    title = (request.POST.get("title") or "").strip()
    description = (request.POST.get("description") or "").strip()
    option_kind = (request.POST.get("option_kind") or DateProposal.OptionKind.DATES).strip()
    audience = (request.POST.get("audience") or DateProposal.Audience.ROOM).strip()
    deadline_raw = (request.POST.get("deadline") or "").strip()
    deadline = parse_date(deadline_raw) if deadline_raw else None
    thread_event_id = request.POST.get("thread_event_id") or None

    options_raw = request.POST.get("options") or "[]"
    try:
        options = json.loads(options_raw)
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Options invalides."}, status=400)
    if not isinstance(options, list):
        return JsonResponse({"ok": False, "error": "Options invalides."}, status=400)

    try:
        _proposal, message = create_and_launch_chat_poll(
            room=room,
            author=request.user,
            title=title,
            description=description,
            option_kind=option_kind,
            audience=audience,
            options=options,
            deadline=deadline,
            thread_event_id=thread_event_id,
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse(
        {"ok": True, "message": serialize_message(message, viewer=request.user)}
    )


@login_required
@require_POST
def api_edit(request: HttpRequest, room_id: int) -> JsonResponse:
    denied = _require_musician(request)
    if denied:
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    if not user_can_access_room(request.user, room):
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    try:
        message_id = int(request.POST.get("message_id") or 0)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Message invalide."}, status=400)
    body = request.POST.get("body", "")
    files = request.FILES.getlist("files")
    remove_attachment_ids = request.POST.getlist("remove_attachment_ids")
    message = get_object_or_404(ChatMessage, pk=message_id, room=room)
    try:
        message = edit_message(
            message=message,
            editor=request.user,
            body=body,
            files=files,
            remove_attachment_ids=remove_attachment_ids,
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse(
        {"ok": True, "message": serialize_message(message, viewer=request.user)}
    )


@login_required
@require_POST
def api_delete(request: HttpRequest, room_id: int) -> JsonResponse:
    denied = _require_musician(request)
    if denied:
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    if not user_can_access_room(request.user, room):
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    try:
        message_id = int(request.POST.get("message_id") or 0)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Message invalide."}, status=400)
    message = get_object_or_404(ChatMessage, pk=message_id, room=room)
    try:
        message = delete_message(message=message, actor=request.user)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse(
        {"ok": True, "message": serialize_message(message, viewer=request.user)}
    )


@login_required
@require_GET
def api_members(request: HttpRequest, room_id: int) -> JsonResponse:
    """Liste des musiciens mentionnables (@) pour le salon."""
    denied = _require_musician(request)
    if denied:
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    if not user_can_access_room(request.user, room):
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    members = serialize_mention_members(room_mention_members(room))
    return JsonResponse({"ok": True, "members": members})


@login_required
@require_POST
def api_react(request: HttpRequest, room_id: int) -> JsonResponse:
    denied = _require_musician(request)
    if denied:
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    if not user_can_access_room(request.user, room):
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    try:
        message_id = int(request.POST.get("message_id") or 0)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Message invalide."}, status=400)
    value = (request.POST.get("value") or "").strip()

    message = get_object_or_404(ChatMessage, pk=message_id, room=room)
    try:
        payload = toggle_reaction(message=message, user=request.user, value=value)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return JsonResponse(
        {
            "ok": True,
            "message_id": message.pk,
            "likes": payload["likes"],
            "mine": payload["mine"],
            "hidden": payload["hidden"],
        }
    )


@login_required
@require_POST
def api_read(request: HttpRequest, room_id: int) -> JsonResponse:
    """Marque le salon comme lu (fallback HTTP si WebSocket indisponible)."""
    denied = _require_musician(request)
    if denied:
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    if not user_can_access_room(request.user, room):
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    if active_membership(room, request.user) is None:
        if request.user.is_staff or request.user.is_superuser:
            ensure_staff_membership(room, request.user)
        else:
            return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    cursor = mark_room_read(room, request.user, broadcast=True)
    return JsonResponse({"ok": True, "cursor": cursor})


def _parse_archive_as_of(raw, fallback):
    """``as_of`` vide / none = curseur d’avant ouverture (aucun watermark)."""
    if raw is None:
        return fallback
    raw = str(raw).strip()
    if raw == "" or raw.lower() in {"none", "null"}:
        return None
    parsed = parse_datetime(raw)
    if parsed is None:
        return fallback
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


@login_required
@require_GET
def api_archive(request: HttpRequest, room_id: int) -> JsonResponse:
    """Messages archivés du salon Orchestre (lus depuis plus d’un mois)."""
    denied = _require_musician(request)
    if denied:
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    if not user_can_access_room(request.user, room):
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)
    if room.kind != ChatRoom.Kind.ORCHESTRA:
        return JsonResponse(
            {"ok": False, "error": "Pas d’archive sur ce salon."}, status=400
        )

    if active_membership(room, request.user) is None:
        if request.user.is_staff or request.user.is_superuser:
            ensure_staff_membership(room, request.user)
        else:
            return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    try:
        membership = ChatMembership.objects.get(
            room=room, user=request.user, left_at__isnull=True
        )
        last_read_at = membership.last_read_at
    except ChatMembership.DoesNotExist:
        last_read_at = None
    last_read_at = _parse_archive_as_of(
        request.GET["as_of"] if "as_of" in request.GET else None,
        last_read_at,
    )

    payload = list_orchestra_archive(
        room,
        request.user,
        last_read_at=last_read_at,
        before_id=request.GET.get("before"),
        include_id=request.GET.get("include"),
        limit=request.GET.get("limit") or 50,
        viewer=request.user,
    )
    return JsonResponse({"ok": True, **payload})


@login_required
@require_GET
def attachment_download(request: HttpRequest, pk: int) -> HttpResponse:
    """Serve chat attachments behind auth (never via public /media/)."""
    denied = _require_musician(request)
    if denied:
        return denied

    att = get_object_or_404(
        ChatAttachment.objects.select_related("message__room"),
        pk=pk,
    )
    room = att.message.room
    if not user_can_access_room(request.user, room):
        return HttpResponseForbidden("Accès refusé.")
    if not att.file:
        return HttpResponseForbidden("Fichier introuvable.")

    as_attachment = not att.is_image
    response = FileResponse(
        att.file.open("rb"),
        as_attachment=as_attachment,
        filename=att.original_name or "fichier",
        content_type=att.content_type or "application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response
