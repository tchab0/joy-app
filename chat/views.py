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
    ensure_staff_membership,
    post_message,
    serialize_message,
    toggle_reaction,
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

    from django.db.models import Count, F, OuterRef, Q, Subquery

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
                filter=Q(room__messages__deleted_at__isnull=True)
                & ~Q(room__messages__author_id=F("user_id"))
                & (
                    Q(last_read_at__isnull=True)
                    | Q(room__messages__created_at__gt=F("last_read_at"))
                ),
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
    rooms = [
        {
            "membership": m,
            "room": m.room,
            "unread": m.unread,
            "last_message": last_by_id.get(m.last_msg_id),
        }
        for m in memberships
    ]
    return render(request, "chat/room_list.html", {"rooms": rooms})


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
    try:
        message = post_message(
            room=room, author=request.user, body=body, files=files
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse(
        {"ok": True, "message": serialize_message(message, viewer=request.user)}
    )


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
