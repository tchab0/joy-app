"""Fréquences d’alertes : défaut utilisateur, overrides type / salon."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import OperationalError, ProgrammingError
from django.utils import timezone

FREQ_REALTIME = "realtime"
FREQ_DAILY = "daily"
FREQ_EVERY_2_DAYS = "every_2_days"
FREQ_EVERY_3_DAYS = "every_3_days"
FREQ_WEEKLY = "weekly"

OVERRIDE_FOLLOW = "default"
OVERRIDE_REALTIME = FREQ_REALTIME
OVERRIDE_DAILY = FREQ_DAILY

DIGEST_FREQUENCIES = frozenset(
    {FREQ_DAILY, FREQ_EVERY_2_DAYS, FREQ_EVERY_3_DAYS, FREQ_WEEKLY}
)
OVERRIDE_FREQUENCIES = frozenset({FREQ_REALTIME, FREQ_DAILY})

TYPE_CHAT = "chat"
TYPE_CHAT_REPLY = "chat_reply"
TYPE_EVENT = "event"
TYPE_PROPOSAL = "proposal"
TYPE_ROADMAP = "event_roadmap"
TYPE_PARTICIPATION = "participation"
TYPE_REHEARSAL = "rehearsal"
TYPE_PHOTOS = "photos"
TYPE_CONTACT = "contact"
TYPE_STAFF_ALERT = "staff_alert"
TYPE_FEEDBACK = "feedback"

# Types exclus du récap inbox (déjà couverts par le digest salon).
# chat_reply reste digéré via l’inbox selon la préf. dédiée.
CHAT_RELATED_TYPES = frozenset({"chat_msg", "chat"})

RELATED_TO_TYPE = {
    "chat_msg": TYPE_CHAT,
    "chat": TYPE_CHAT,
    "chat_reply": TYPE_CHAT_REPLY,
    "event": TYPE_EVENT,
    "proposal": TYPE_PROPOSAL,
    "event_roadmap": TYPE_ROADMAP,
    "participation": TYPE_PARTICIPATION,
    "rehearsal": TYPE_REHEARSAL,
    "photos": TYPE_PHOTOS,
    "contact": TYPE_CONTACT,
    "staff_alert": TYPE_STAFF_ALERT,
    "feedback": TYPE_FEEDBACK,
}

WEEKDAY_LABELS = (
    (0, "Lundi"),
    (1, "Mardi"),
    (2, "Mercredi"),
    (3, "Jeudi"),
    (4, "Vendredi"),
    (5, "Samedi"),
    (6, "Dimanche"),
)

HOUR_CHOICES = tuple((h, f"{h:02d}h") for h in range(24))


@dataclass(frozen=True)
class NotifyTypeSpec:
    key: str
    label: str
    help_text: str
    staff_only: bool = False


TYPE_CATALOG: tuple[NotifyTypeSpec, ...] = (
    NotifyTypeSpec(
        TYPE_EVENT,
        "Concerts et dates",
        "Invitations / convocations aux concerts et autres dates (hors répétitions).",
    ),
    NotifyTypeSpec(
        TYPE_REHEARSAL,
        "Répétitions",
        "Création d’une répétition à laquelle vous êtes attendu·e.",
    ),
    NotifyTypeSpec(
        TYPE_PROPOSAL,
        "Sondages de disponibilité",
        "Lancement d’un sondage et rappels avant la deadline.",
    ),
    NotifyTypeSpec(
        TYPE_ROADMAP,
        "Feuilles de route",
        "Publication ou mise à jour d’une feuille de route.",
    ),
    NotifyTypeSpec(
        TYPE_PARTICIPATION,
        "Relances de disponibilité",
        "Relances « peut-être » et propositions de remplacement.",
    ),
    NotifyTypeSpec(
        TYPE_PHOTOS,
        "Demandes de photos",
        "Rappel après un événement pour partager photos et vidéos.",
    ),
    NotifyTypeSpec(
        TYPE_FEEDBACK,
        "Retours utilisateurs",
        "Nouveaux retours (staff) et réponses du staff sur vos propres retours.",
    ),
    NotifyTypeSpec(
        TYPE_CHAT,
        "Chat — réglage commun",
        "Messages de salon sans exception individuelle ci-dessous. "
        "Les @mentions restent toujours immédiates.",
    ),
    NotifyTypeSpec(
        TYPE_CHAT_REPLY,
        "Réponses à mes messages",
        "Quand quelqu’un répond à un de vos messages (hors @mention). "
        "Temps réel, une fois par jour, ou suivre le réglage par défaut.",
    ),
    NotifyTypeSpec(
        TYPE_CONTACT,
        "Messages de contact",
        "Formulaire public (contact et prestations).",
        staff_only=True,
    ),
    NotifyTypeSpec(
        TYPE_STAFF_ALERT,
        "Annulations de présence",
        "Un musicien confirme qu’il ne viendra plus.",
        staff_only=True,
    ),
)

TYPE_LABELS = {spec.key: spec.label for spec in TYPE_CATALOG}

STAFF_ONLY_TYPES = frozenset(spec.key for spec in TYPE_CATALOG if spec.staff_only)


def is_staff_only_notify_type(notify_type: str) -> bool:
    """True si le type d’alerte est réservé au staff (ex. annulations de présence)."""
    key = pref_type_for_related(notify_type or "")
    return key in STAFF_ONLY_TYPES


def user_is_staff_recipient(user) -> bool:
    return bool(
        user is not None
        and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    )



@dataclass
class DeliveryPolicy:
    frequency: str
    hour: int
    weekday: int | None
    last_sent_at: datetime | None
    source: str  # "default" | "type" | "room"

    @property
    def is_realtime(self) -> bool:
        return self.frequency == FREQ_REALTIME


def types_for_user(user) -> list[NotifyTypeSpec]:
    staff = bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    return [spec for spec in TYPE_CATALOG if staff or not spec.staff_only]


def pref_type_for_related(related_type: str) -> str:
    key = (related_type or "").strip()
    return RELATED_TO_TYPE.get(key, key)


def digest_is_due(
    frequency: str,
    hour: int,
    weekday: int | None,
    last_sent_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    """True si un récap doit partir à ``now`` (heure locale du site)."""
    if frequency == FREQ_REALTIME:
        return True
    if frequency not in DIGEST_FREQUENCIES:
        return False

    now = now or timezone.now()
    local = timezone.localtime(now)
    hour = int(hour)
    today_slot = local.replace(hour=hour, minute=0, second=0, microsecond=0)

    if frequency == FREQ_WEEKLY:
        if weekday is None:
            return False
        if local.weekday() != int(weekday):
            return False
        if local < today_slot:
            return False
        if last_sent_at is None:
            return True
        return timezone.localtime(last_sent_at) < today_slot

    if frequency == FREQ_DAILY:
        if local < today_slot:
            return False
        if last_sent_at is None:
            return True
        return timezone.localtime(last_sent_at) < today_slot

    interval = 2 if frequency == FREQ_EVERY_2_DAYS else 3
    if last_sent_at is None:
        return local >= today_slot
    last_local = timezone.localtime(last_sent_at)
    last_slot = last_local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if last_local >= last_slot:
        next_slot = last_slot + timedelta(days=interval)
    else:
        next_slot = last_slot
    return local >= next_slot


def resolve_delivery(
    user,
    notify_type: str = "",
    room=None,
    *,
    membership=None,
    type_pref=None,
) -> DeliveryPolicy:
    """
    Room override > type override > défaut utilisateur.
    Tolère un schéma pas encore migré → temps réel.
    """
    default = _default_policy(user)
    try:
        if room is not None:
            membership = membership or _membership_for(user, room)
            room_policy = _policy_from_membership(membership, default)
            if room_policy is not None:
                return room_policy

        ntype = pref_type_for_related(notify_type)
        if ntype:
            type_pref = type_pref or _type_pref_for(user, ntype)
            type_policy = _policy_from_type_pref(type_pref, default)
            if type_policy is not None:
                return type_policy
    except (ProgrammingError, OperationalError):
        return default
    return default


def should_deliver_immediately(
    user,
    notify_type: str = "",
    room=None,
    *,
    force: bool = False,
) -> bool:
    if force:
        return True
    try:
        return resolve_delivery(user, notify_type, room).is_realtime
    except (ProgrammingError, OperationalError):
        return True
    except Exception:
        return True


def _default_policy(user) -> DeliveryPolicy:
    freq = getattr(user, "notify_frequency", None) or FREQ_REALTIME
    hour = getattr(user, "notify_digest_hour", None)
    if hour is None:
        hour = 18
    weekday = getattr(user, "notify_digest_weekday", None)
    if weekday is None:
        weekday = 0
    return DeliveryPolicy(
        frequency=freq,
        hour=int(hour),
        weekday=int(weekday),
        last_sent_at=getattr(user, "notify_digest_last_sent_at", None),
        source="default",
    )


def _membership_for(user, room):
    from chat.models import ChatMembership

    return (
        ChatMembership.objects.filter(user_id=user.pk, room_id=room.pk).first()
        if room is not None
        else None
    )


def _type_pref_for(user, notify_type: str):
    from users.models import NotificationTypePref

    return (
        NotificationTypePref.objects.filter(
            user_id=user.pk, notify_type=notify_type
        ).first()
    )


def _policy_from_membership(membership, default: DeliveryPolicy) -> DeliveryPolicy | None:
    if membership is None:
        return None
    raw = (getattr(membership, "notify_frequency_override", None) or "").strip()
    if raw not in OVERRIDE_FREQUENCIES:
        return None
    hour = getattr(membership, "notify_digest_hour", None)
    if hour is None:
        hour = default.hour
    return DeliveryPolicy(
        frequency=raw,
        hour=int(hour),
        weekday=default.weekday,
        last_sent_at=getattr(membership, "notify_digest_last_sent_at", None),
        source="room",
    )


def _policy_from_type_pref(type_pref, default: DeliveryPolicy) -> DeliveryPolicy | None:
    if type_pref is None:
        return None
    raw = (getattr(type_pref, "frequency", None) or "").strip()
    if raw not in OVERRIDE_FREQUENCIES:
        return None
    hour = getattr(type_pref, "digest_hour", None)
    if hour is None:
        hour = default.hour
    return DeliveryPolicy(
        frequency=raw,
        hour=int(hour),
        weekday=default.weekday,
        last_sent_at=getattr(type_pref, "last_sent_at", None),
        source="type",
    )


def mark_policy_sent(
    user,
    policy: DeliveryPolicy,
    *,
    now=None,
    membership=None,
    type_pref=None,
    notify_type: str = "",
) -> None:
    """Enregistre l’heure d’envoi du récap pour le seau concerné."""
    if policy.is_realtime:
        return
    now = now or timezone.now()
    if policy.source == "room" and membership is not None:
        membership.notify_digest_last_sent_at = now
        membership.save(update_fields=["notify_digest_last_sent_at"])
        return
    if policy.source == "type":
        pref = type_pref
        if pref is None and notify_type:
            pref = _type_pref_for(user, notify_type)
        if pref is not None:
            pref.last_sent_at = now
            pref.save(update_fields=["last_sent_at"])
        return
    user.notify_digest_last_sent_at = now
    user.save(update_fields=["notify_digest_last_sent_at"])


def _parse_hour(raw, fallback: int = 18) -> int | None:
    try:
        hour = int(raw)
    except (TypeError, ValueError):
        return None
    if 0 <= hour <= 23:
        return hour
    return None


def save_notification_overrides(user, post, *, memberships) -> list[str]:
    """
    Persiste les overrides type / salon depuis un QueryDict POST.
    Retourne une liste d’erreurs (vide si OK).
    """
    from users.models import NotificationTypePref

    errors: list[str] = []
    default_hour = int(getattr(user, "notify_digest_hour", 18) or 18)

    # Types
    wanted_types = {spec.key for spec in types_for_user(user)}
    existing = {
        p.notify_type: p
        for p in NotificationTypePref.objects.filter(user=user)
    }
    for key in wanted_types:
        mode = (post.get(f"ov_type_{key}") or OVERRIDE_FOLLOW).strip()
        if mode == OVERRIDE_FOLLOW or mode == "":
            if key in existing:
                existing[key].delete()
            continue
        if mode not in OVERRIDE_FREQUENCIES:
            errors.append(f"Fréquence invalide pour « {TYPE_LABELS.get(key, key)} ».")
            continue
        hour = default_hour
        if mode == OVERRIDE_DAILY:
            parsed = _parse_hour(post.get(f"ov_type_{key}_hour"), default_hour)
            if parsed is None:
                errors.append(
                    f"Heure invalide pour « {TYPE_LABELS.get(key, key)} »."
                )
                continue
            hour = parsed
        pref = existing.get(key)
        if pref is None:
            NotificationTypePref.objects.create(
                user=user,
                notify_type=key,
                frequency=mode,
                digest_hour=hour if mode == OVERRIDE_DAILY else None,
            )
        else:
            pref.frequency = mode
            pref.digest_hour = hour if mode == OVERRIDE_DAILY else None
            pref.save(update_fields=["frequency", "digest_hour"])

    # Salons
    for membership in memberships:
        mode = (
            post.get(f"ov_room_{membership.pk}") or OVERRIDE_FOLLOW
        ).strip()
        fields = []
        if mode == OVERRIDE_FOLLOW or mode == "":
            if membership.notify_frequency_override:
                membership.notify_frequency_override = ""
                membership.notify_digest_hour = None
                fields = ["notify_frequency_override", "notify_digest_hour"]
        elif mode not in OVERRIDE_FREQUENCIES:
            errors.append(f"Fréquence invalide pour « {membership.room.title} ».")
            continue
        else:
            hour = default_hour
            if mode == OVERRIDE_DAILY:
                parsed = _parse_hour(
                    post.get(f"ov_room_{membership.pk}_hour"), default_hour
                )
                if parsed is None:
                    errors.append(f"Heure invalide pour « {membership.room.title} ».")
                    continue
                hour = parsed
            membership.notify_frequency_override = mode
            membership.notify_digest_hour = (
                hour if mode == OVERRIDE_DAILY else None
            )
            fields = ["notify_frequency_override", "notify_digest_hour"]
        if fields:
            membership.save(update_fields=fields)

    return errors
