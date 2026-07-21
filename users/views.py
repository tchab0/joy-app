from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (
    IdentifierAuthenticationForm,
    OTPVerifyForm,
    PasswordlessStartForm,
    ProfileSecurityForm,
    StaffContactNotifyPrefsForm,
    TwoFactorChannelForm,
)
from .models import AuthChallenge, User
from .otp import (
    available_2fa_channels,
    challenge_public_payload,
    create_challenge,
    generate_totp_secret,
    pick_2fa_channel,
    sign_pending_2fa,
    totp_provisioning_uri,
    unsign_pending_2fa,
    verify_challenge,
    verify_totp,
)
from .roles import (
    ROLE_LABELS,
    get_user_roles,
    user_can_access_member_area,
    user_can_access_planning,
)

logger = logging.getLogger(__name__)

SESSION_PENDING_2FA = "auth_pending_2fa"
SESSION_PENDING_LOGIN_CHALLENGE = "auth_login_challenge"


def _safe_next(request: HttpRequest) -> str:
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return reverse("account_home")


@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect(_safe_next(request))

    password_form = IdentifierAuthenticationForm(
        request, data=request.POST if request.method == "POST" and request.POST.get("mode") == "password" else None
    )
    otp_form = PasswordlessStartForm(
        data=request.POST if request.method == "POST" and request.POST.get("mode") == "otp" else None
    )

    if request.method == "POST":
        mode = request.POST.get("mode")
        if mode == "password" and password_form.is_valid():
            user = password_form.get_user()
            if user.two_factor_enabled:
                return _begin_two_factor(request, user)
            login(request, user)
            messages.success(request, "Connexion réussie.")
            return redirect(_safe_next(request))

        if mode == "otp" and otp_form.is_valid():
            user = otp_form.cleaned_data["user"]
            channel = otp_form.cleaned_data["channel"]
            if user is None:
                messages.info(
                    request,
                    "Si un compte correspond, un code vient d’être envoyé.",
                )
                return redirect("account_login")
            try:
                if not request.session.session_key:
                    request.session.create()
                challenge, _ = create_challenge(
                    user=user,
                    purpose=AuthChallenge.Purpose.LOGIN,
                    channel=channel,
                    session_key=request.session.session_key or "",
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                request.session[SESSION_PENDING_LOGIN_CHALLENGE] = str(challenge.id)
                messages.info(
                    request,
                    f"Un code a été envoyé ({challenge_public_payload(challenge)['destination_masked']}).",
                )
                return redirect("account_login_otp")

    return render(
        request,
        "users/login.html",
        {
            "password_form": password_form,
            "otp_form": otp_form,
            "next": request.GET.get("next", ""),
        },
    )


def _begin_two_factor(request: HttpRequest, user: User) -> HttpResponse:
    try:
        channel = pick_2fa_channel(user)
        challenge, _ = create_challenge(
            user=user,
            purpose=AuthChallenge.Purpose.TWO_FACTOR,
            channel=channel,
            session_key=request.session.session_key or "",
            send=channel != AuthChallenge.Channel.APP,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("account_login")

    token = sign_pending_2fa(user.pk, str(challenge.id))
    request.session[SESSION_PENDING_2FA] = token
    return redirect("account_login_2fa")


@require_http_methods(["GET", "POST"])
def login_otp_view(request: HttpRequest) -> HttpResponse:
    challenge_id = request.session.get(SESSION_PENDING_LOGIN_CHALLENGE)
    if not challenge_id:
        messages.error(request, "Session de connexion expirée. Recommencez.")
        return redirect("account_login")

    challenge = get_object_or_404(AuthChallenge, pk=challenge_id)
    form = OTPVerifyForm(
        data=request.POST or None,
        initial={"challenge_id": challenge.id},
    )

    if request.method == "POST" and form.is_valid():
        if str(form.cleaned_data["challenge_id"]) != str(challenge.id):
            messages.error(request, "Défi invalide.")
            return redirect("account_login")
        if verify_challenge(challenge, form.cleaned_data["code"]):
            login(request, challenge.user, backend="django.contrib.auth.backends.ModelBackend")
            request.session.pop(SESSION_PENDING_LOGIN_CHALLENGE, None)
            if challenge.user.two_factor_enabled and challenge.purpose == AuthChallenge.Purpose.LOGIN:
                # OTP login already proves possession of email/phone; skip 2FA if same channel
                pass
            messages.success(request, "Connexion réussie.")
            return redirect(_safe_next(request))
        messages.error(request, "Code incorrect ou expiré.")

    return render(
        request,
        "users/verify_otp.html",
        {
            "form": form,
            "challenge": challenge_public_payload(challenge),
            "title": "Entrez le code reçu",
            "resend_url": reverse("account_login"),
        },
    )


@require_http_methods(["GET", "POST"])
def login_2fa_view(request: HttpRequest) -> HttpResponse:
    token = request.session.get(SESSION_PENDING_2FA)
    payload = unsign_pending_2fa(token) if token else None
    if not payload:
        messages.error(request, "Session de double authentification expirée.")
        return redirect("account_login")

    user = get_object_or_404(User, pk=payload["uid"], is_active=True)
    challenge = get_object_or_404(AuthChallenge, pk=payload["cid"], user=user)

    channel_form = TwoFactorChannelForm(user, data=request.POST if request.POST.get("action") == "switch" else None)
    otp_form = OTPVerifyForm(
        data=request.POST if request.POST.get("action") != "switch" else None,
        initial={"challenge_id": challenge.id, "pending_token": token},
    )

    if request.method == "POST" and request.POST.get("action") == "switch" and channel_form.is_valid():
        try:
            channel = pick_2fa_channel(user, channel_form.cleaned_data["channel"])
            challenge, _ = create_challenge(
                user=user,
                purpose=AuthChallenge.Purpose.TWO_FACTOR,
                channel=channel,
                session_key=request.session.session_key or "",
                send=channel != AuthChallenge.Channel.APP,
            )
            request.session[SESSION_PENDING_2FA] = sign_pending_2fa(user.pk, str(challenge.id))
            messages.info(request, "Nouveau code envoyé." if channel != "app" else "Utilisez votre application.")
            return redirect("account_login_2fa")
        except ValueError as exc:
            messages.error(request, str(exc))

    if request.method == "POST" and request.POST.get("action") != "switch" and otp_form.is_valid():
        if verify_challenge(challenge, otp_form.cleaned_data["code"]):
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            request.session.pop(SESSION_PENDING_2FA, None)
            messages.success(request, "Connexion réussie.")
            return redirect(_safe_next(request))
        messages.error(request, "Code incorrect ou expiré.")

    return render(
        request,
        "users/verify_2fa.html",
        {
            "otp_form": otp_form,
            "channel_form": channel_form,
            "challenge": challenge_public_payload(challenge),
            "channels": available_2fa_channels(user),
        },
    )


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    messages.info(request, "Vous êtes déconnecté.")
    return redirect("home")


@login_required
def account_home(request: HttpRequest) -> HttpResponse:
    from feedback.services.page_feedback import (
        build_page_feedback_author_responses_context,
        build_page_feedback_vote_requests_context,
    )

    staff_notify_form = None
    if request.user.is_staff or request.user.is_superuser:
        if (
            request.method == "POST"
            and request.POST.get("action") == "staff_notify"
        ):
            staff_notify_form = StaffContactNotifyPrefsForm(
                request.POST, instance=request.user
            )
            if staff_notify_form.is_valid():
                staff_notify_form.save()
                messages.success(
                    request, "Préférence de notification enregistrée."
                )
                return redirect("account_home")
        else:
            staff_notify_form = StaffContactNotifyPrefsForm(
                instance=request.user
            )

    roles = get_user_roles(request.user)
    context = {
        "roles": [ROLE_LABELS[r] for r in roles if r in ROLE_LABELS],
        "can_planning": user_can_access_planning(request.user),
        "can_members": user_can_access_member_area(request.user),
        "staff_notify_form": staff_notify_form,
    }
    context.update(build_page_feedback_author_responses_context(request.user))
    context.update(build_page_feedback_vote_requests_context(request.user))
    return render(request, "users/account.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def security_view(request: HttpRequest) -> HttpResponse:
    user = request.user
    form = ProfileSecurityForm(request.POST or None, instance=user)

    if request.method == "POST" and request.POST.get("action") == "save" and form.is_valid():
        form.save()
        messages.success(request, "Préférences de sécurité enregistrées.")
        return redirect("account_security")

    pending_secret = request.session.get("pending_totp_secret")
    return render(
        request,
        "users/security.html",
        {
            "form": form,
            "totp_enabled": user.totp_enabled,
            "pending_secret": pending_secret,
            "pending_uri": totp_provisioning_uri(user, pending_secret) if pending_secret else "",
            "channels": available_2fa_channels(user),
        },
    )


@login_required
@require_POST
def totp_setup_start(request: HttpRequest) -> HttpResponse:
    secret = generate_totp_secret()
    request.session["pending_totp_secret"] = secret
    messages.info(request, "Scannez le secret dans votre application, puis validez avec un code.")
    return redirect("account_security")


@login_required
@require_POST
def totp_setup_confirm(request: HttpRequest) -> HttpResponse:
    secret = request.session.get("pending_totp_secret")
    code = (request.POST.get("code") or "").strip()
    if not secret:
        messages.error(request, "Aucune configuration en cours.")
        return redirect("account_security")
    if not verify_totp(secret, code):
        messages.error(request, "Code application incorrect.")
        return redirect("account_security")

    user = request.user
    user.totp_secret = secret
    user.totp_enabled = True
    user.preferred_2fa_channel = User.Preferred2FA.APP
    user.save(update_fields=["totp_secret", "totp_enabled", "preferred_2fa_channel"])
    request.session.pop("pending_totp_secret", None)
    messages.success(request, "Application d’authentification activée.")
    return redirect("account_security")


@login_required
@require_POST
def totp_disable(request: HttpRequest) -> HttpResponse:
    user = request.user
    user.totp_secret = ""
    user.totp_enabled = False
    if user.preferred_2fa_channel == User.Preferred2FA.APP:
        user.preferred_2fa_channel = User.Preferred2FA.EMAIL
    user.save(update_fields=["totp_secret", "totp_enabled", "preferred_2fa_channel"])
    messages.success(request, "Application d’authentification désactivée.")
    return redirect("account_security")


@login_required
def member_area(request: HttpRequest) -> HttpResponse:
    if not user_can_access_member_area(request.user):
        messages.error(request, "Espace réservé aux adhérents.")
        return redirect("account_home")
    return render(request, "users/member_area.html")
