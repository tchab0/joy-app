from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import (
    FileResponse,
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from chat.models import ChatAttachment, ChatMembership, ChatMessage, ChatRoom
from chat.services import (
    active_membership,
    build_room_embed_context,
    edit_message,
    ensure_staff_membership,
    ensure_staff_room,
    mark_room_read,
    post_message,
    room_mention_members,
    serialize_mention_member,
    serialize_message,
    sync_user_to_staff_room,
    toggle_reaction,
    unread_messages_filter,
    user_can_access_room,
)
from users.forms import ChatNotificationPrefsForm
from users.roles import user_can_access_planning


def _require_musician(request: HttpRequest) -> HttpResponse | None:
    if not request.user.is_authenticated:
        return redirect("account_login")
    if not user_can_access_planning(request.user):
        return HttpResponseForbidden("Accès réservé aux musiciens.")
    return None


@login_required
@require_GET
def room_list(request: HttpRequest) -> HttpResponse:
    denied = _require_musician(request)
    if denied:
        return denied

    if request.user.is_staff or request.user.is_superuser:
        sync_user_to_staff_room(request.user)

    from django.db.models import Count, OuterRef, Subquery

    last_msg = ChatMessage.objects.filter(
        room_id=OuterRef("room_id"), deleted_at__isnull=True
    ).order_by("-created_at")
    memberships = list(
        ChatMembership.objects.filter(user=request.user, left_at__isnull=True)
        .select_related("room", "room__event", "room__piece")
        .annotate(
            last_msg_id=Subquery(last_msg.values("pk")[:1]),
            unread=Count(
                "room__messages",
                filter=unread_messages_filter(),
                distinct=True,
            ),
        )
        .order_by("room__kind", "-room__created_at")
    )
    last_ids = [m.last_msg_id for m in memberships if m.last_msg_id]
    last_by_id = {
        msg.pk: msg
        for msg in ChatMessage.objects.filter(pk__in=last_ids).select_related("author")
    }

    def _sort_key(item: dict):
        last = item["last_message"]
        last_ts = last.created_at.timestamp() if last else 0.0
        kind_rank = {
            ChatRoom.Kind.ORCHESTRA: 0,
            ChatRoom.Kind.STAFF: 1,
            ChatRoom.Kind.PIECE: 2,
            ChatRoom.Kind.EVENT: 3,
        }.get(item["room"].kind, 9)
        return (
            0 if item["unread"] else 1,
            kind_rank,
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
        }
        kind = m.room.kind
        if kind == ChatRoom.Kind.PIECE:
            piece_rooms.append(item)
        elif kind == ChatRoom.Kind.EVENT:
            event_rooms.append(item)
        else:
            primary_rooms.append(item)

    primary_rooms.sort(key=_sort_key)
    piece_rooms.sort(key=_sort_key)
    event_rooms.sort(key=_sort_key)

    piece_unread_total = sum(i["unread"] for i in piece_rooms)
    event_unread_total = sum(i["unread"] for i in event_rooms)

    return render(
        request,
        "chat/room_list.html",
        {
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
    denied = _require_musician(request)
    if denied:
        return denied
    if not (request.user.is_staff or request.user.is_superuser):
        return HttpResponseForbidden("Salon réservé au staff.")
    room = ensure_staff_room()
    sync_user_to_staff_room(request.user)
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
            if room.kind in {ChatRoom.Kind.ORCHESTRA, ChatRoom.Kind.STAFF}:
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
    return render(request, "chat/room_detail.html", ctx)


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
    denied = _require_musician(request)
    if denied:
        return denied
    form = ChatNotificationPrefsForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Préférences de notifications enregistrées.")
        return redirect("chat:prefs")
    return render(request, "chat/account_prefs.html", {"form": form})


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
@require_GET
def api_members(request: HttpRequest, room_id: int) -> JsonResponse:
    """Liste des musiciens mentionnables (@) pour le salon."""
    denied = _require_musician(request)
    if denied:
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    if not user_can_access_room(request.user, room):
        return JsonResponse({"ok": False, "error": "Accès refusé"}, status=403)

    members = [
        serialize_mention_member(u) for u in room_mention_members(room)
    ]
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
