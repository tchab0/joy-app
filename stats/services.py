from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone


PERIOD_CHOICES = (
    (7, "7 jours"),
    (30, "30 jours"),
    (90, "90 jours"),
)

FEATURE_LABELS = {
    "planning.view": "Planning",
    "planning.moi": "Planning — moi",
    "planning.polls": "Sondages",
    "planning.admin": "Planning admin",
    "planning.propose": "Proposer une date",
    "chat.view": "Chat",
    "repertoire.view": "Répertoire",
    "repertoire.staff": "Atelier répertoire",
    "repertoire.pdf": "Téléchargements PDF",
    "repertoire.audio": "Écoutes audio",
    "compte.view": "Compte",
    "feedback.view": "Feedback",
}


@dataclass(frozen=True)
class Period:
    days: int
    since: Any
    label: str


def resolve_period(raw: str | None) -> Period:
    try:
        days = int(raw or "30")
    except (TypeError, ValueError):
        days = 30
    allowed = {d for d, _ in PERIOD_CHOICES}
    if days not in allowed:
        days = 30
    label = dict(PERIOD_CHOICES)[days]
    since = timezone.now() - timedelta(days=days)
    return Period(days=days, since=since, label=label)


def _series_from_trunc(qs, date_field: str) -> list[dict[str, Any]]:
    rows = (
        qs.annotate(day=TruncDate(date_field))
        .values("day")
        .annotate(n=Count("id"))
        .order_by("day")
    )
    return [
        {"date": row["day"].isoformat() if row["day"] else "", "count": row["n"]}
        for row in rows
        if row["day"]
    ]


def _safe_usage_qs(since):
    try:
        from stats.models import UsageEvent

        return UsageEvent.objects.filter(created_at__gte=since)
    except Exception:
        return None


def _safe_public_views_qs(since):
    try:
        from stats.models import PublicPageView

        return PublicPageView.objects.filter(created_at__gte=since)
    except Exception:
        return None


def build_dashboard_context(*, period: Period, ga_id: str = "") -> dict[str, Any]:
    from django.contrib.auth import get_user_model

    from chat.models import ChatMessage, ChatMembership
    from core.models import ContactMessage, MediaVote
    from feedback.models import PageFeedback
    from planning.models import DateVote, EventParticipation, MusicianProfile
    from users.models import PushSubscription

    User = get_user_model()
    since = period.since
    now = timezone.now()

    musicians = User.objects.filter(is_musician=True, is_active=True)
    musician_count = musicians.count()

    login_buckets = {
        "7j": musicians.filter(last_login__gte=now - timedelta(days=7)).count(),
        "30j": musicians.filter(last_login__gte=now - timedelta(days=30)).count(),
        "90j": musicians.filter(last_login__gte=now - timedelta(days=90)).count(),
        "never": musicians.filter(last_login__isnull=True).count(),
        "stale_90": musicians.filter(
            Q(last_login__lt=now - timedelta(days=90)) | Q(last_login__isnull=True)
        ).count(),
    }

    inactive_qs = musicians.filter(
        Q(last_login__lt=now - timedelta(days=90)) | Q(last_login__isnull=True)
    ).select_related("musician_profile", "musician_profile__section")
    # Jamais connectés d’abord, puis plus anciennes connexions.
    inactive_musicians = sorted(
        inactive_qs[:80],
        key=lambda u: (u.last_login is not None, u.last_login or now),
    )[:40]

    participations_period = EventParticipation.objects.filter(updated_at__gte=since)
    participation_by_status = list(
        participations_period.values("status__code", "status__label")
        .annotate(n=Count("id"))
        .order_by("-n")
    )

    responders = (
        participations_period.exclude(status__code="invited")
        .values("user_id")
        .distinct()
        .count()
    )
    invited_only = (
        EventParticipation.objects.filter(
            updated_at__gte=since,
            status__code="invited",
        )
        .values("user_id")
        .distinct()
        .count()
    )

    chat_msgs = ChatMessage.objects.filter(created_at__gte=since)
    chat_message_count = chat_msgs.count()
    chat_authors = (
        chat_msgs.exclude(author_id=None).values("author_id").distinct().count()
    )
    chat_series = _series_from_trunc(chat_msgs, "created_at")
    top_rooms = list(
        chat_msgs.values("room__title")
        .annotate(n=Count("id"))
        .order_by("-n")[:8]
    )
    silent_members = (
        ChatMembership.objects.filter(left_at__isnull=True)
        .filter(
            Q(last_read_at__isnull=True) | Q(last_read_at__lt=since),
            user__is_musician=True,
            user__is_active=True,
        )
        .values("user_id")
        .distinct()
        .count()
    )

    poll_votes = DateVote.objects.filter(updated_at__gte=since).count()
    poll_voters = (
        DateVote.objects.filter(updated_at__gte=since)
        .values("user_id")
        .distinct()
        .count()
    )

    push_users = (
        PushSubscription.objects.filter(user__is_musician=True, user__is_active=True)
        .values("user_id")
        .distinct()
        .count()
    )
    tours_done = musicians.filter(tour_musician_version__gte=1).count()

    contacts = ContactMessage.objects.filter(created_at__gte=since)
    contact_by_kind = list(
        contacts.values("kind").annotate(n=Count("id")).order_by("-n")
    )
    contact_by_status = list(
        contacts.values("statut").annotate(n=Count("id")).order_by("-n")
    )
    contact_series = _series_from_trunc(contacts, "created_at")
    media_votes = MediaVote.objects.filter(created_at__gte=since).count()
    top_media = list(
        MediaVote.objects.filter(created_at__gte=since)
        .values("media__titre")
        .annotate(n=Count("id"))
        .order_by("-n")[:8]
    )

    feedbacks = PageFeedback.objects.filter(created_at__gte=since)
    feedback_count = feedbacks.count()
    feedback_by_cat = list(
        feedbacks.values("category").annotate(n=Count("id")).order_by("-n")
    )
    feedback_by_page = list(
        feedbacks.values("page_url", "page_title")
        .annotate(n=Count("id"))
        .order_by("-n")[:10]
    )

    public_qs = _safe_public_views_qs(since)
    pageviews = 0
    unique_visitors = 0
    public_series: list[dict[str, Any]] = []
    top_pages: list[dict[str, Any]] = []
    if public_qs is not None:
        pageviews = public_qs.count()
        unique_visitors = (
            public_qs.exclude(session_key="")
            .values("session_key")
            .distinct()
            .count()
        )
        public_series = _series_from_trunc(public_qs, "created_at")
        top_pages = [
            {"path": row["path"] or "/", "count": row["n"]}
            for row in public_qs.values("path").annotate(n=Count("id")).order_by("-n")[:15]
        ]

    profile_count = MusicianProfile.objects.filter(user__is_active=True).count()

    # Phase B — usage events
    usage_qs = _safe_usage_qs(since)
    feature_ranking: list[dict[str, Any]] = []
    usage_series: list[dict[str, Any]] = []
    usage_unique_users = 0
    usage_total = 0
    if usage_qs is not None:
        usage_total = usage_qs.count()
        usage_unique_users = (
            usage_qs.exclude(user_id=None).values("user_id").distinct().count()
        )
        for row in (
            usage_qs.values("name").annotate(n=Count("id")).order_by("-n")
        ):
            feature_ranking.append(
                {
                    "name": row["name"],
                    "label": FEATURE_LABELS.get(row["name"], row["name"]),
                    "count": row["n"],
                }
            )
        usage_series = _series_from_trunc(usage_qs, "created_at")

    kind_labels = dict(ContactMessage.KIND_CHOICES)
    status_labels = dict(ContactMessage.STATUS_CHOICES)
    cat_labels = dict(PageFeedback.CATEGORY_CHOICES)

    return {
        "period": period,
        "period_choices": PERIOD_CHOICES,
        "ga_configured": bool(ga_id),
        "ga_id": ga_id,
        "visitors": {
            "pageviews": pageviews,
            "unique_visitors": unique_visitors,
            "public_series": public_series,
            "top_pages": top_pages,
            "contacts_total": contacts.count(),
            "contact_by_kind": [
                {
                    "key": row["kind"],
                    "label": kind_labels.get(row["kind"], row["kind"]),
                    "count": row["n"],
                }
                for row in contact_by_kind
            ],
            "contact_by_status": [
                {
                    "key": row["statut"],
                    "label": status_labels.get(row["statut"], row["statut"]),
                    "count": row["n"],
                }
                for row in contact_by_status
            ],
            "contact_series": contact_series,
            "media_votes": media_votes,
            "top_media": [
                {"title": row["media__titre"] or "—", "count": row["n"]}
                for row in top_media
            ],
            "feedback_count": feedback_count,
            "feedback_by_cat": [
                {
                    "key": row["category"],
                    "label": cat_labels.get(row["category"], row["category"]),
                    "count": row["n"],
                }
                for row in feedback_by_cat
            ],
            "feedback_by_page": feedback_by_page,
        },
        "musicians": {
            "count": musician_count,
            "profiles": profile_count,
            "login_buckets": login_buckets,
            "inactive": inactive_musicians,
            "participation_by_status": [
                {
                    "code": row["status__code"],
                    "label": row["status__label"] or row["status__code"],
                    "count": row["n"],
                }
                for row in participation_by_status
            ],
            "responders": responders,
            "invited_only_users": invited_only,
            "chat_messages": chat_message_count,
            "chat_authors": chat_authors,
            "chat_series": chat_series,
            "top_rooms": [
                {"title": row["room__title"] or "—", "count": row["n"]}
                for row in top_rooms
            ],
            "silent_chat_members": silent_members,
            "poll_votes": poll_votes,
            "poll_voters": poll_voters,
            "push_users": push_users,
            "tours_done": tours_done,
        },
        "usage": {
            "total": usage_total,
            "unique_users": usage_unique_users,
            "ranking": feature_ranking,
            "series": usage_series,
            "retention_days": getattr(settings, "USAGE_EVENT_RETENTION_DAYS", 90),
            "available": usage_qs is not None,
        },
        "insights": _build_insights(
            musician_count=musician_count,
            login_buckets=login_buckets,
            feature_ranking=feature_ranking,
            chat_authors=chat_authors,
            push_users=push_users,
            poll_voters=poll_voters,
            feedback_by_page=feedback_by_page,
        ),
    }


def _build_insights(
    *,
    musician_count: int,
    login_buckets: dict,
    feature_ranking: list,
    chat_authors: int,
    push_users: int,
    poll_voters: int,
    feedback_by_page: list,
) -> list[dict[str, str]]:
    tips: list[dict[str, str]] = []
    if musician_count:
        stale_pct = round(100 * login_buckets["stale_90"] / musician_count)
        if stale_pct >= 25:
            tips.append(
                {
                    "kind": "prune",
                    "text": (
                        f"{login_buckets['stale_90']} musicien(s) sans connexion "
                        f"depuis 90 j ({stale_pct} %) — candidats à un nettoyage de comptes."
                    ),
                }
            )
        if login_buckets["never"]:
            tips.append(
                {
                    "kind": "prune",
                    "text": (
                        f"{login_buckets['never']} compte(s) musicien jamais connecté(s)."
                    ),
                }
            )
        push_pct = round(100 * push_users / musician_count)
        if push_pct < 30:
            tips.append(
                {
                    "kind": "develop",
                    "text": (
                        f"Push activé pour {push_users}/{musician_count} "
                        f"({push_pct} %) — à promouvoir dans le compte."
                    ),
                }
            )

    if feature_ranking:
        top = feature_ranking[0]
        tips.append(
            {
                "kind": "develop",
                "text": f"Feature la plus utilisée : {top['label']} ({top['count']} hits).",
            }
        )
        low = [f for f in feature_ranking if f["count"] <= max(2, feature_ranking[0]["count"] // 20)]
        if len(feature_ranking) >= 3 and low:
            names = ", ".join(f["label"] for f in low[:3])
            tips.append(
                {
                    "kind": "prune",
                    "text": f"Peu utilisées sur la période : {names}.",
                }
            )
    else:
        tips.append(
            {
                "kind": "info",
                "text": (
                    "Le suivi des pages (Phase B) commencera à remplir "
                    "le classement des features après navigation des musiciens."
                ),
            }
        )

    if musician_count and chat_authors < max(1, musician_count // 4):
        tips.append(
            {
                "kind": "develop",
                "text": (
                    f"Seulement {chat_authors} auteur(s) chat actifs — "
                    "le chat est peut‑être sous‑adopté."
                ),
            }
        )
    if poll_voters and musician_count and poll_voters < musician_count // 3:
        tips.append(
            {
                "kind": "develop",
                "text": (
                    f"{poll_voters} votant(s) aux sondages — "
                    "relancer les non‑répondeurs peut aider."
                ),
            }
        )
    if feedback_by_page:
        top_fb = feedback_by_page[0]
        title = top_fb.get("page_title") or top_fb.get("page_url") or "—"
        tips.append(
            {
                "kind": "develop",
                "text": (
                    f"Page la plus signalée : {title} "
                    f"({top_fb['n']} retours)."
                ),
            }
        )
    return tips
