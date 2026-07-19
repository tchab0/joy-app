from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from chat.models import ChatMembership, ChatMessage, ChatRoom
from chat.services import (
    active_membership,
    mark_room_read,
    post_message,
    serialize_message,
    unread_count,
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

    memberships = (
        ChatMembership.objects.filter(user=request.user, left_at__isnull=True)
        .select_related("room", "room__event")
        .order_by("room__kind", "-room__created_at")
    )
    rooms = []
    for m in memberships:
        last = (
            ChatMessage.objects.filter(room=m.room, deleted_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        rooms.append(
            {
                "membership": m,
                "room": m.room,
                "unread": unread_count(m),
                "last_message": last,
            }
        )
    return render(request, "chat/room_list.html", {"rooms": rooms})


@login_required
@require_http_methods(["GET", "POST"])
def room_detail(request: HttpRequest, room_id: int) -> HttpResponse:
    denied = _require_musician(request)
    if denied:
        return denied

    room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
    membership = active_membership(room, request.user)
    is_staff = request.user.is_staff or request.user.is_superuser
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
        membership, _ = ChatMembership.objects.get_or_create(
            room=room,
            user=request.user,
            defaults={"subscribed": False},
        )
        if membership.left_at:
            membership.rejoin(subscribed=False)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "subscribe":
            membership.subscribed = True
            membership.save(update_fields=["subscribed"])
            messages.success(request, "Alertes SMS activées pour ce salon.")
            return redirect("chat:room", room_id=room.pk)
        if action == "unsubscribe":
            membership.subscribed = False
            membership.save(update_fields=["subscribed"])
            messages.success(request, "Alertes SMS désactivées pour ce salon.")
            return redirect("chat:room", room_id=room.pk)
        if action == "leave":
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

    mark_room_read(room, request.user)
    # Historique complet à l’entrée du salon (pas de plafond).
    history = list(
        ChatMessage.objects.filter(room=room)
        .select_related("author")
        .prefetch_related("attachments")
        .order_by("created_at")
    )

    participation = None
    show_leave_hint = False
    if room.event_id:
        participation = (
            request.user.event_participations.filter(event_id=room.event_id)
            .select_related("status")
            .first()
        )
        if participation and participation.status.code == "declined":
            show_leave_hint = True

    ws_scheme = "wss" if request.is_secure() else "ws"
    ws_url = f"{ws_scheme}://{request.get_host()}/ws/chat/{room.pk}/"

    return render(
        request,
        "chat/room_detail.html",
        {
            "room": room,
            "membership": membership,
            "messages": history,
            "messages_json": json.dumps(
                [serialize_message(m) for m in history], ensure_ascii=False
            ),
            "participation": participation,
            "show_leave_hint": show_leave_hint,
            "ws_url": ws_url,
            "current_user_id": request.user.pk,
        },
    )


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
    try:
        message = post_message(
            room=room, author=request.user, body=body, files=files
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, "message": serialize_message(message)})
