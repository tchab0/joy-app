"""Génération / vérification OTP et TOTP (sans dépendance externe lourde)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone

from .models import AuthChallenge, User
from .phone import mask_destination, normalize_phone
from .sms import send_sms

OTP_LENGTH = 6
OTP_TTL_SECONDS = 10 * 60
OTP_RATE_LIMIT_SECONDS = 60
TOTP_PERIOD = 30
TOTP_DIGITS = 6
TOTP_WINDOW = 1


def _pepper() -> str:
    return getattr(settings, "OTP_PEPPER", None) or settings.SECRET_KEY


def hash_code(code: str) -> str:
    return hashlib.sha256(f"{_pepper()}:{code.strip()}".encode()).hexdigest()


def generate_numeric_code(length: int = OTP_LENGTH) -> str:
    upper = 10**length
    return f"{secrets.randbelow(upper):0{length}d}"


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp_at(secret_b32: str, for_time: int | None = None) -> str:
    # Pad base32 if stripped
    padded = secret_b32.upper() + "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    counter = int((for_time if for_time is not None else time.time()) // TOTP_PERIOD)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code_int % (10 ** TOTP_DIGITS):0{TOTP_DIGITS}d}"


def verify_totp(secret_b32: str, code: str) -> bool:
    if not secret_b32 or not code:
        return False
    code = code.strip().replace(" ", "")
    now = int(time.time())
    for drift in range(-TOTP_WINDOW, TOTP_WINDOW + 1):
        if hmac.compare_digest(_totp_at(secret_b32, now + drift * TOTP_PERIOD), code):
            return True
    return False


def totp_provisioning_uri(user: User, secret: str) -> str:
    issuer = getattr(settings, "TOTP_ISSUER", "Jazz Orchestra Yonnais")
    label = user.email or user.username
    from urllib.parse import quote

    return (
        f"otpauth://totp/{quote(issuer)}:{quote(label)}"
        f"?secret={secret}&issuer={quote(issuer)}&digits={TOTP_DIGITS}&period={TOTP_PERIOD}"
    )


def _rate_limit_key(user_id, purpose: str, channel: str) -> str:
    return f"otp-rate:{user_id}:{purpose}:{channel}"


def can_send_otp(user: User, purpose: str, channel: str) -> bool:
    return cache.get(_rate_limit_key(user.pk, purpose, channel)) is None


def mark_otp_sent(user: User, purpose: str, channel: str) -> None:
    cache.set(
        _rate_limit_key(user.pk, purpose, channel),
        1,
        timeout=OTP_RATE_LIMIT_SECONDS,
    )


def invalidate_open_challenges(user: User, purpose: str) -> None:
    AuthChallenge.objects.filter(
        user=user,
        purpose=purpose,
        consumed_at__isnull=True,
    ).update(consumed_at=timezone.now())


def create_challenge(
    *,
    user: User,
    purpose: str,
    channel: str,
    session_key: str = "",
    send: bool = True,
) -> tuple[AuthChallenge, str | None]:
    """
    Crée un défi OTP. Retourne (challenge, code_clair_ou_None).
    Pour le canal app, aucun code n’est envoyé (TOTP côté client).
    """
    if channel == AuthChallenge.Channel.APP:
        challenge = AuthChallenge.objects.create(
            user=user,
            purpose=purpose,
            channel=channel,
            code_hash="",
            destination="app",
            expires_at=timezone.now() + timedelta(minutes=10),
            session_key=session_key or "",
        )
        return challenge, None

    if not can_send_otp(user, purpose, channel):
        raise ValueError("Veuillez patienter avant de redemander un code.")

    code = generate_numeric_code()
    if channel == AuthChallenge.Channel.EMAIL:
        destination = (user.email or "").strip().lower()
        if not destination:
            raise ValueError("Aucun e-mail associé à ce compte.")
    elif channel == AuthChallenge.Channel.NOTIFICATION:
        destination = normalize_phone(user.phone)
        if not destination:
            raise ValueError("Aucun téléphone associé à ce compte.")
    else:
        raise ValueError("Canal invalide.")

    invalidate_open_challenges(user, purpose)
    challenge = AuthChallenge.objects.create(
        user=user,
        purpose=purpose,
        channel=channel,
        code_hash=hash_code(code),
        destination=destination,
        expires_at=timezone.now() + timedelta(seconds=OTP_TTL_SECONDS),
        session_key=session_key or "",
    )

    if send:
        try:
            _deliver_code(user, challenge, code)
        except Exception as exc:
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=["consumed_at"])
            raise ValueError(
                "Impossible d’envoyer le code pour le moment. Réessayez plus tard."
            ) from exc
        mark_otp_sent(user, purpose, channel)

    return challenge, code


def _deliver_code(user: User, challenge: AuthChallenge, code: str) -> None:
    if challenge.channel == AuthChallenge.Channel.EMAIL:
        send_mail(
            subject="Votre code de connexion — Jazz Orchestra Yonnais",
            message=(
                f"Bonjour {user.get_full_name() or user.username},\n\n"
                f"Votre code est : {code}\n"
                f"Il expire dans {OTP_TTL_SECONDS // 60} minutes.\n\n"
                "Si vous n’êtes pas à l’origine de cette demande, ignorez cet e-mail.\n"
                "— Jazz Orchestra Yonnais"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[challenge.destination],
            fail_silently=False,
        )
    elif challenge.channel == AuthChallenge.Channel.NOTIFICATION:
        send_sms(
            challenge.destination,
            f"JOY — code {code} (valide {OTP_TTL_SECONDS // 60} min)",
        )


def verify_challenge(
    challenge: AuthChallenge,
    code: str,
    *,
    consume: bool = True,
) -> bool:
    if not challenge.is_usable:
        return False

    challenge.attempts += 1
    challenge.save(update_fields=["attempts"])

    if challenge.channel == AuthChallenge.Channel.APP:
        ok = bool(challenge.user.totp_enabled and verify_totp(challenge.user.totp_secret, code))
    else:
        ok = hmac.compare_digest(challenge.code_hash, hash_code(code))

    if not ok:
        return False

    if consume:
        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=["consumed_at"])
        if challenge.channel == AuthChallenge.Channel.EMAIL:
            if not challenge.user.email_verified:
                challenge.user.email_verified = True
                challenge.user.save(update_fields=["email_verified"])
        elif challenge.channel == AuthChallenge.Channel.NOTIFICATION:
            if not challenge.user.phone_verified:
                challenge.user.phone_verified = True
                challenge.user.save(update_fields=["phone_verified"])
    return True


def find_user_by_identifier(identifier: str) -> User | None:
    value = (identifier or "").strip()
    if not value:
        return None

    qs = User.objects.filter(is_active=True)
    if "@" in value:
        return qs.filter(email__iexact=value).first()

    phone = normalize_phone(value)
    if phone:
        by_phone = qs.filter(phone=phone).first()
        if by_phone:
            return by_phone

    return qs.filter(username__iexact=value).first()


def available_2fa_channels(user: User) -> list[str]:
    channels: list[str] = []
    if user.totp_enabled and user.totp_secret:
        channels.append(AuthChallenge.Channel.APP)
    if user.email:
        channels.append(AuthChallenge.Channel.EMAIL)
    if normalize_phone(user.phone):
        channels.append(AuthChallenge.Channel.NOTIFICATION)
    return channels


def pick_2fa_channel(user: User, requested: str | None = None) -> str:
    available = available_2fa_channels(user)
    if not available:
        raise ValueError("Aucun canal de double authentification disponible.")
    if requested and requested in available:
        return requested
    preferred = user.preferred_2fa_channel
    if preferred in available:
        return preferred
    return available[0]


def challenge_public_payload(challenge: AuthChallenge) -> dict:
    return {
        "id": str(challenge.id),
        "channel": challenge.channel,
        "destination_masked": mask_destination(challenge.destination, challenge.channel),
        "expires_at": challenge.expires_at.isoformat(),
    }


# Jetons signés de session 2FA (étape intermédiaire après mot de passe)
TWO_FACTOR_SALT = "users.two_factor.v1"


def sign_pending_2fa(user_id: int, challenge_id: str) -> str:
    return signing.dumps(
        {"uid": user_id, "cid": challenge_id},
        salt=TWO_FACTOR_SALT,
        compress=True,
    )


def unsign_pending_2fa(token: str, max_age: int = 600) -> dict | None:
    try:
        return signing.loads(token, salt=TWO_FACTOR_SALT, max_age=max_age)
    except signing.BadSignature:
        return None
