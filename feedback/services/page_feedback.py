# SPDX-License-Identifier: AGPL-3.0-or-later
"""Retours utilisateurs — soumission pied de page et affichage dashboard admin."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
import json
import math
from typing import Any

from django.db.models import Case, Count, F, IntegerField, Q, Value, When
from django.urls import reverse
from django.utils import timezone

from feedback.models import PageFeedback, PageFeedbackRating, PageFeedbackVote

CATEGORY_DISPLAY = {
    PageFeedback.CATEGORY_BUG: {
        'label': 'Bug',
        'css_class': 'fb-cat fb-cat-bug',
        'accent_bar_class': 'fb-accent-bug',
    },
    PageFeedback.CATEGORY_COMFORT: {
        'label': 'Confort de la vue',
        'css_class': 'fb-cat fb-cat-comfort',
        'accent_bar_class': 'fb-accent-comfort',
    },
    PageFeedback.CATEGORY_MISSING_FEATURE: {
        'label': 'Fonctionnalité manquante',
        'css_class': 'fb-cat fb-cat-feature',
        'accent_bar_class': 'fb-accent-feature',
    },
}

DASHBOARD_FEEDBACK_LIMIT = 50
PENDING_FEEDBACK_COLLAPSE_THRESHOLD = 5
PAGE_CONTEXT_MAX_LENGTH = 2000

FEEDBACK_SORT_DATE_DESC = 'date_desc'
FEEDBACK_SORT_DATE_ASC = 'date_asc'
FEEDBACK_SORT_USER = 'user'
FEEDBACK_SORT_IMPORTANCE_DESC = 'importance_desc'
FEEDBACK_SORT_IMPORTANCE_ASC = 'importance_asc'
FEEDBACK_SORT_PRIORITY_DESC = 'priority_desc'
FEEDBACK_SORT_PRIORITY_ASC = 'priority_asc'
DEFAULT_FEEDBACK_SORT = FEEDBACK_SORT_DATE_DESC

FEEDBACK_VIEW_PENDING = 'pending'
FEEDBACK_VIEW_IN_PROGRESS = 'in_progress'
FEEDBACK_VIEW_SNOOZED = 'snoozed'
FEEDBACK_VIEW_TREATED = 'treated'
DEFAULT_FEEDBACK_VIEW = FEEDBACK_VIEW_PENDING

FEEDBACK_SORT_CHOICES = (
    (FEEDBACK_SORT_DATE_DESC, 'Date (récent → ancien)'),
    (FEEDBACK_SORT_DATE_ASC, 'Date (ancien → récent)'),
    (FEEDBACK_SORT_USER, 'Utilisateur'),
    (FEEDBACK_SORT_IMPORTANCE_DESC, 'Importance (élevée → faible)'),
    (FEEDBACK_SORT_IMPORTANCE_ASC, 'Importance (faible → élevée)'),
    (FEEDBACK_SORT_PRIORITY_DESC, 'Priorité admin (élevée → faible)'),
    (FEEDBACK_SORT_PRIORITY_ASC, 'Priorité admin (faible → élevée)'),
)

IMPORTANCE_LABELS = {
    1: 'Pas important',
    5: 'Très important',
}

ADMIN_PRIORITY_LABELS = {
    1: 'Faible',
    5: 'Urgent',
}

AUTHOR_RESPONSE_MESSAGES = {
    PageFeedback.CATEGORY_BUG: ('Votre retour a été pris en compte, le bug est normalement corrigé.'),
    PageFeedback.CATEGORY_COMFORT: ('Votre retour a été pris en compte, vous pouvez tester la version améliorée.'),
    PageFeedback.CATEGORY_MISSING_FEATURE: (
        'Votre retour a été pris en compte, vous pouvez tester la version améliorée.'
    ),
}

AUTHOR_RESPONSES_LIMIT = 20
PENDING_FEEDBACK_LIMIT = 30
VOTE_REQUESTS_LIMIT = 20

VOTABLE_FEEDBACK_CATEGORIES = (
    PageFeedback.CATEGORY_COMFORT,
    PageFeedback.CATEGORY_MISSING_FEATURE,
)

# Borne inférieure d'un intervalle crédible bayésien à 90 % (Evan Miller, 2014).
BAYESIAN_IMPORTANCE_Z = 1.65
STAR_RATINGS = (1, 2, 3, 4, 5)


def _round_importance_average(avg: float | Decimal) -> int:
    return int(Decimal(str(avg)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _score_to_decimal(score: float) -> Decimal:
    return Decimal(str(score)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


def compute_bayesian_importance_score(
    rating_values: list[int],
    *,
    z: float = BAYESIAN_IMPORTANCE_Z,
) -> float | None:
    """
    Combine la note moyenne (1–5) et l'effectif des votes via une borne inférieure
    bayésienne (prior uniforme sur les étoiles, Evan Miller 2014).
    Les retours peu soutenus sont pénalisés ; les notes convergent avec plus de votes.
    """
    if not rating_values:
        return None

    counts = Counter(rating_values)
    vote_count = len(rating_values)
    star_count = len(STAR_RATINGS)

    weighted_mean = sum(star * (counts.get(star, 0) + 1) for star in STAR_RATINGS) / (vote_count + star_count)
    weighted_mean_sq = sum(star * star * (counts.get(star, 0) + 1) for star in STAR_RATINGS) / (vote_count + star_count)
    variance = (weighted_mean_sq - weighted_mean**2) / (vote_count + star_count + 1)
    if variance < 0:
        variance = 0.0

    lower_bound = weighted_mean - z * math.sqrt(variance)
    return max(1.0, min(5.0, lower_bound))


def recompute_feedback_importance(feedback: PageFeedback) -> int | None:
    """Recalcule le score bayésien et l'importance affichée (1 à 5)."""
    rating_values = list(feedback.ratings.values_list('importance', flat=True))
    score = compute_bayesian_importance_score(rating_values)
    if score is None:
        feedback.importance = None
        feedback.importance_score = None
    else:
        feedback.importance_score = _score_to_decimal(score)
        feedback.importance = _round_importance_average(score)
    feedback.save(update_fields=['importance', 'importance_score'])
    return feedback.importance


def feedback_is_snoozed(feedback: PageFeedback, *, now=None) -> bool:
    """Retour actuellement reporté (date de réapparition dans le futur)."""
    if feedback.snoozed_until is None:
        return False
    now = now or timezone.now()
    return feedback.snoozed_until > now


def exclude_active_snoozes(queryset, *, now=None):
    """Exclut les retours dont le report est encore actif."""
    now = now or timezone.now()
    return queryset.filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lte=now))


def active_snoozed_feedback_filter(*, now=None) -> Q:
    now = now or timezone.now()
    return Q(snoozed_until__gt=now)


def parse_snooze_until_date(raw_date: str | None) -> datetime | None:
    """Convertit une date ISO (YYYY-MM-DD) en début de journée locale."""
    if not raw_date:
        return None
    try:
        parsed = date.fromisoformat(raw_date.strip())
    except ValueError:
        return None
    local_tz = timezone.get_current_timezone()
    local_start = datetime.combine(parsed, time.min)
    if timezone.is_naive(local_start):
        local_start = timezone.make_aware(local_start, local_tz)
    return local_start


def pending_page_feedback_queryset(*, page_url: str, category: str | None = None):
    qs = (
        PageFeedback.objects.filter(
            treated_at__isnull=True,
            in_progress_at__isnull=True,
            page_url=(page_url or '')[:500],
        )
        .annotate(supporter_count=Count('ratings', distinct=True))
        .select_related('author')
        .order_by(F('importance_score').desc(nulls_last=True), '-created_at')
    )
    if category:
        qs = qs.filter(category=category)
    return qs


def _pending_feedback_item(feedback: PageFeedback, *, user) -> dict[str, Any]:
    user_rating = None
    if user and user.is_authenticated:
        rating = feedback.ratings.filter(user=user).first()
        if rating:
            user_rating = rating.importance
    supporter_count = getattr(feedback, 'supporter_count', None)
    if supporter_count is None:
        supporter_count = feedback.ratings.count()
    return {
        'id': feedback.id,
        'message': feedback.message,
        'message_preview': feedback.message[:160],
        'importance': feedback.importance,
        'supporter_count': supporter_count,
        'user_rating': user_rating,
        'is_own': bool(user and user.is_authenticated and feedback.author_id == user.id),
    }


def build_pending_page_feedback_items(
    *,
    page_url: str,
    category: str | None = None,
    user=None,
    limit: int = PENDING_FEEDBACK_LIMIT,
) -> list[dict[str, Any]]:
    qs = pending_page_feedback_queryset(page_url=page_url, category=category)[:limit]
    items = []
    for fb in qs:
        item = _pending_feedback_item(fb, user=user)
        if not item['is_own']:
            items.append(item)
    return items


def rate_page_feedback(
    *,
    feedback_id: int,
    user,
    importance: int,
) -> PageFeedback | None:
    """Ajoute ou met à jour le vote d'un utilisateur sur un retour en attente."""
    if importance not in dict(PageFeedback.IMPORTANCE_CHOICES):
        return None

    feedback = PageFeedback.objects.filter(
        pk=feedback_id,
        treated_at__isnull=True,
        in_progress_at__isnull=True,
    ).first()
    if feedback is None:
        return None

    PageFeedbackRating.objects.update_or_create(
        feedback=feedback,
        user=user,
        defaults={'importance': importance},
    )
    recompute_feedback_importance(feedback)
    return feedback


def build_page_feedback_footer_context(
    *,
    page_url: str,
    nav_profile: str = '',
    nav_profile_label: str = '',
) -> dict[str, Any]:
    return {
        'page_feedback_page_url': page_url,
        'page_feedback_nav_profile': nav_profile,
        'page_feedback_nav_profile_label': nav_profile_label,
    }


def can_manage_page_feedback(user, **_kwargs) -> bool:
    """Retours admin : réservé au staff JOY."""
    return bool(getattr(user, 'is_authenticated', False) and getattr(user, 'is_staff', False))


def parse_feedback_sort(sort_key: str | None) -> str:
    valid = {choice[0] for choice in FEEDBACK_SORT_CHOICES}
    if sort_key in valid:
        return sort_key
    return DEFAULT_FEEDBACK_SORT


def parse_feedback_view(view_key: str | None) -> str:
    if view_key == FEEDBACK_VIEW_TREATED:
        return FEEDBACK_VIEW_TREATED
    if view_key == FEEDBACK_VIEW_IN_PROGRESS:
        return FEEDBACK_VIEW_IN_PROGRESS
    if view_key == FEEDBACK_VIEW_SNOOZED:
        return FEEDBACK_VIEW_SNOOZED
    return FEEDBACK_VIEW_PENDING


def feedback_category_ordering() -> list:
    """Tri tertiaire admin : bugs, puis fonctionnalités manquantes, puis confort."""
    return [
        Case(
            When(category=PageFeedback.CATEGORY_BUG, then=Value(0)),
            When(category=PageFeedback.CATEGORY_MISSING_FEATURE, then=Value(1)),
            When(category=PageFeedback.CATEGORY_COMFORT, then=Value(2)),
            default=Value(99),
            output_field=IntegerField(),
        )
    ]


def feedback_is_new(feedback: PageFeedback) -> bool:
    """Retour non lu admin : statut nouveau sans priorité admin définie."""
    return feedback.status == PageFeedback.STATUS_NEW and feedback.admin_priority is None


def feedback_new_status_ordering() -> list:
    """Tri primaire admin : nouveaux (non lus sans priorité) avant le reste."""
    return [
        Case(
            When(
                status=PageFeedback.STATUS_NEW,
                admin_priority__isnull=True,
                then=Value(0),
            ),
            default=Value(1),
            output_field=IntegerField(),
        )
    ]


def feedback_sort_ordering(sort_key: str) -> list:
    sort_key = parse_feedback_sort(sort_key)
    if sort_key == FEEDBACK_SORT_DATE_ASC:
        return ['created_at']
    if sort_key == FEEDBACK_SORT_USER:
        return ['author__last_name', 'author__first_name', '-created_at']
    if sort_key == FEEDBACK_SORT_IMPORTANCE_DESC:
        return [
            F('importance_score').desc(nulls_last=True),
            *feedback_category_ordering(),
            '-created_at',
        ]
    if sort_key == FEEDBACK_SORT_IMPORTANCE_ASC:
        return [
            F('importance_score').asc(nulls_last=True),
            *feedback_category_ordering(),
            '-created_at',
        ]
    if sort_key == FEEDBACK_SORT_PRIORITY_DESC:
        return [F('admin_priority').desc(nulls_last=True), '-created_at']
    if sort_key == FEEDBACK_SORT_PRIORITY_ASC:
        return [F('admin_priority').asc(nulls_last=True), '-created_at']
    return ['-created_at']


def ordered_pending_page_feedback(queryset, *, limit: int) -> list[PageFeedback]:
    """
    Retours en attente :
      1. les nouveaux (non lus sans priorité), du plus récent au plus ancien ;
      2. puis les autres par priorité admin décroissante (étoiles violettes) ;
      3. à priorité égale : bug, puis fonctionnalité manquante, puis confort ;
      4. en dernier recours, du plus récent au plus ancien.
    """
    new_feedback = queryset.filter(
        status=PageFeedback.STATUS_NEW,
        admin_priority__isnull=True,
    ).order_by('-created_at')
    rest = queryset.filter(Q(status=PageFeedback.STATUS_READ) | Q(admin_priority__isnull=False)).order_by(
        F('admin_priority').desc(nulls_last=True),
        *feedback_category_ordering(),
        '-created_at',
    )

    result = list(new_feedback[:limit])
    remaining = limit - len(result)
    if remaining > 0:
        result.extend(rest[:remaining])
    return result


def page_feedback_dom_id(feedback_id: int) -> str:
    return f'page-feedback-{feedback_id}'


def parse_feedback_focus(raw_focus: str | None) -> int | None:
    if not raw_focus or not str(raw_focus).strip().isdigit():
        return None
    return int(str(raw_focus).strip())


def feedback_rows_for_admin_view(
    *,
    view: str | None = None,
    sort: str | None = None,
    limit: int = DASHBOARD_FEEDBACK_LIMIT,
) -> tuple[str, str, list[PageFeedback]]:
    """Retours affichés sur le dashboard admin, dans l'ordre de la liste."""
    sort = parse_feedback_sort(sort)
    view = parse_feedback_view(view)
    now = timezone.now()
    qs = PageFeedback.objects.select_related('author').annotate(supporter_count=Count('ratings', distinct=True))
    if view == FEEDBACK_VIEW_TREATED:
        qs = qs.filter(treated_at__isnull=False)
        feedback_rows = list(qs.order_by(*feedback_sort_ordering(sort))[:limit])
    elif view == FEEDBACK_VIEW_IN_PROGRESS:
        qs = exclude_active_snoozes(qs.filter(in_progress_at__isnull=False, treated_at__isnull=True), now=now)
        feedback_rows = list(qs.order_by(*feedback_sort_ordering(sort))[:limit])
    elif view == FEEDBACK_VIEW_SNOOZED:
        qs = qs.filter(active_snoozed_feedback_filter(now=now), treated_at__isnull=True)
        feedback_rows = list(qs.order_by('snoozed_until', '-created_at')[:limit])
        sort = DEFAULT_FEEDBACK_SORT
    else:
        qs = exclude_active_snoozes(qs.filter(treated_at__isnull=True, in_progress_at__isnull=True), now=now)
        feedback_rows = ordered_pending_page_feedback(qs, limit=limit)
        sort = DEFAULT_FEEDBACK_SORT
    return view, sort, feedback_rows


def resolve_feedback_focus_after_action(
    *,
    acted_feedback_id: int,
    view: str | None = None,
    sort: str | None = None,
    leaves_current_list: bool,
) -> int | None:
    """
    Cible de défilement après action admin.
    Si le retour quitte la liste courante, focalise le suivant (ou le précédent si dernier).
    Sinon, conserve le retour traité.

    Appeler avant la mutation BDD lorsque ``leaves_current_list`` est vrai.
    """
    _view, _sort, feedback_rows = feedback_rows_for_admin_view(view=view, sort=sort)
    current_ids = [feedback.id for feedback in feedback_rows]
    if acted_feedback_id not in current_ids:
        return None

    if not leaves_current_list:
        return acted_feedback_id

    index = current_ids.index(acted_feedback_id)
    remaining_ids = [feedback_id for feedback_id in current_ids if feedback_id != acted_feedback_id]
    if not remaining_ids:
        return None
    if index < len(remaining_ids):
        return remaining_ids[index]
    return remaining_ids[-1]


def dashboard_feedback_redirect_url(
    sort: str | None = None,
    view: str | None = None,
    *,
    focus_feedback_id: int | None = None,
) -> str:
    view = parse_feedback_view(view)
    base = reverse('admin_feedback')
    params: list[str] = []
    if view in (FEEDBACK_VIEW_TREATED, FEEDBACK_VIEW_IN_PROGRESS, FEEDBACK_VIEW_SNOOZED):
        sort = parse_feedback_sort(sort)
        if sort != DEFAULT_FEEDBACK_SORT:
            params.append(f'feedback_sort={sort}')
    if view != DEFAULT_FEEDBACK_VIEW:
        params.append(f'feedback_view={view}')
    if focus_feedback_id:
        params.append(f'feedback_focus={focus_feedback_id}')
    if params:
        return f'{base}?{"&".join(params)}#retours-utilisateurs'
    return f'{base}#retours-utilisateurs'


def redirect_url_after_feedback_admin_action(
    *,
    acted_feedback_id: int,
    sort: str | None,
    view: str | None,
    leaves_current_list: bool,
) -> str:
    focus_feedback_id = resolve_feedback_focus_after_action(
        acted_feedback_id=acted_feedback_id,
        view=view,
        sort=sort,
        leaves_current_list=leaves_current_list,
    )
    return dashboard_feedback_redirect_url(sort, view, focus_feedback_id=focus_feedback_id)


def author_response_message(category: str) -> str:
    return AUTHOR_RESPONSE_MESSAGES.get(
        category,
        'Votre retour a été pris en compte.',
    )


def resolve_feedback_page_info(request, data) -> dict[str, str]:
    """Consolide URL, titre et contexte JSON de la page signalée."""
    from feedback.roles import role_labels_for_user

    page_url = (data.get('page_url') or '').strip() or request.get_full_path()
    page_title = (data.get('page_title') or '').strip()

    ctx: dict[str, Any] = {}
    raw_context = (data.get('page_context') or '').strip()
    if raw_context:
        try:
            parsed = json.loads(raw_context)
            if isinstance(parsed, dict):
                ctx = parsed
        except json.JSONDecodeError:
            ctx = {}

    if not page_title:
        page_title = str(ctx.get('title') or '').strip()

    referer = request.META.get('HTTP_REFERER', '')
    profile_key = str(ctx.get('profile_key') or '').strip()
    profile_label = str(ctx.get('profile') or '').strip()
    if request.user.is_authenticated and not profile_key:
        labels = role_labels_for_user(request.user)
        profile_key = ','.join(labels.keys())[:20]
        profile_label = ', '.join(labels.values())[:100] or profile_label

    full_context = {
        'title': page_title[:200],
        'path': (str(ctx.get('path') or page_url))[:500],
        'href': str(ctx.get('href') or referer or '')[:500],
        'profile': profile_label[:100],
        'profile_key': profile_key[:20],
    }
    if not page_title:
        page_title = full_context['title']

    page_context_json = json.dumps(full_context, ensure_ascii=False)
    if len(page_context_json) > PAGE_CONTEXT_MAX_LENGTH:
        page_context_json = page_context_json[:PAGE_CONTEXT_MAX_LENGTH]

    return {
        'page_url': full_context['path'],
        'page_title': page_title[:200],
        'page_context': page_context_json,
    }


def _parse_page_context(feedback: PageFeedback) -> dict[str, Any]:
    if not feedback.page_context:
        return {}
    try:
        parsed = json.loads(feedback.page_context)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def feedback_is_votable_category(category: str) -> bool:
    return category in VOTABLE_FEEDBACK_CATEGORIES


def feedback_vote_is_open(feedback: PageFeedback) -> bool:
    return feedback.vote_opened_at is not None and feedback.vote_closed_at is None


def _feedback_vote_role_choices(feedback: PageFeedback) -> list[dict[str, Any]]:
    from feedback.roles import VOTE_ROLE_LABELS as NAV_PROFILE_LABELS

    selected = set(feedback.vote_roles or [])
    return [{'key': key, 'label': label, 'checked': key in selected} for key, label in NAV_PROFILE_LABELS.items()]


def _feedback_vote_role_labels(feedback: PageFeedback) -> list[str]:
    from feedback.roles import VOTE_ROLE_LABELS as NAV_PROFILE_LABELS

    return [NAV_PROFILE_LABELS[key] for key in (feedback.vote_roles or []) if key in NAV_PROFILE_LABELS]


def user_can_participate_in_feedback_vote(user, feedback: PageFeedback) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if not feedback_is_votable_category(feedback.category):
        return False
    if not feedback_vote_is_open(feedback):
        return False
    from feedback.roles import get_available_vote_roles as get_available_nav_profiles

    user_profiles = set(get_available_nav_profiles(user))
    vote_roles = set(feedback.vote_roles or [])
    return bool(user_profiles & vote_roles)


def _feedback_vote_counts(feedback: PageFeedback) -> tuple[int, int]:
    for_count = feedback.votes.filter(choice=PageFeedbackVote.VOTE_FOR).count()
    against_count = feedback.votes.filter(choice=PageFeedbackVote.VOTE_AGAINST).count()
    return for_count, against_count


def _feedback_row(feedback: PageFeedback) -> dict[str, Any]:
    category = CATEGORY_DISPLAY.get(feedback.category, {'label': feedback.category, 'css_class': ''})
    author = feedback.author
    author_name = f'{author.last_name} {author.first_name}'.strip() or author.username
    page_ctx = _parse_page_context(feedback)
    page_title = feedback.page_title or str(page_ctx.get('title') or '')
    page_profile = str(page_ctx.get('profile') or '')
    page_href = str(page_ctx.get('href') or feedback.page_url)
    vote_for_count, vote_against_count = _feedback_vote_counts(feedback)
    vote_formulation = (feedback.vote_formulation or '').strip() or feedback.message
    return {
        'id': feedback.id,
        'category': feedback.category,
        'category_label': category['label'],
        'category_css_class': category['css_class'],
        'accent_bar_class': category.get('accent_bar_class', 'bg-violet-500'),
        'author_name': author_name,
        'author_username': author.username,
        'message': feedback.message,
        'importance': feedback.importance,
        'importance_label': IMPORTANCE_LABELS.get(feedback.importance, ''),
        'supporter_count': getattr(feedback, 'supporter_count', feedback.ratings.count()),
        'admin_priority': feedback.admin_priority,
        'admin_priority_label': ADMIN_PRIORITY_LABELS.get(feedback.admin_priority, ''),
        'page_url': feedback.page_url,
        'page_title': page_title,
        'page_profile': page_profile,
        'page_href': page_href,
        'created_at': feedback.created_at,
        'is_unread': feedback_is_new(feedback),
        'is_author_notified': feedback.author_notified_at is not None,
        'author_notified_at': feedback.author_notified_at,
        'can_notify_author': feedback.author_notified_at is None,
        'is_treated': feedback.treated_at is not None,
        'treated_at': feedback.treated_at,
        'is_in_progress': feedback.in_progress_at is not None,
        'in_progress_at': feedback.in_progress_at,
        'is_snoozed': feedback_is_snoozed(feedback),
        'snoozed_until': feedback.snoozed_until,
        'snoozed_at': feedback.snoozed_at,
        'show_snooze_form': feedback.treated_at is None and not feedback_is_snoozed(feedback),
        'show_unsnooze_form': feedback_is_snoozed(feedback) and feedback.treated_at is None,
        'snooze_min_date': (timezone.localdate() + timedelta(days=1)).isoformat(),
        'show_vote_admin': feedback_is_votable_category(feedback.category),
        'vote_formulation': vote_formulation,
        'vote_role_choices': _feedback_vote_role_choices(feedback),
        'vote_role_labels': _feedback_vote_role_labels(feedback),
        'vote_is_open': feedback_vote_is_open(feedback),
        'vote_was_opened': feedback.vote_opened_at is not None,
        'vote_opened_at': feedback.vote_opened_at,
        'vote_closed_at': feedback.vote_closed_at,
        'show_close_vote': feedback_vote_is_open(feedback),
        'show_reopen_vote': feedback.vote_opened_at is not None and feedback.vote_closed_at is not None,
        'vote_for_count': vote_for_count,
        'vote_against_count': vote_against_count,
        'vote_total_count': vote_for_count + vote_against_count,
    }


def _author_response_row(feedback: PageFeedback) -> dict[str, Any]:
    category = CATEGORY_DISPLAY.get(feedback.category, {'label': feedback.category, 'css_class': ''})
    page_ctx = _parse_page_context(feedback)
    page_title = feedback.page_title or str(page_ctx.get('title') or '')
    return {
        'id': feedback.id,
        'category_label': category['label'],
        'category_css_class': category['css_class'],
        'accent_bar_class': category.get('accent_bar_class', 'sc-accent-bar--stgab-teal'),
        'message': feedback.message,
        'response_message': author_response_message(feedback.category),
        'notified_at': feedback.author_notified_at,
        'page_url': feedback.page_url,
        'page_title': page_title,
    }


def _vote_request_row(feedback: PageFeedback) -> dict[str, Any]:
    category = CATEGORY_DISPLAY.get(feedback.category, {'label': feedback.category, 'css_class': ''})
    page_ctx = _parse_page_context(feedback)
    page_title = feedback.page_title or str(page_ctx.get('title') or '')
    formulation = (feedback.vote_formulation or '').strip()
    return {
        'id': feedback.id,
        'category_label': category['label'],
        'category_css_class': category['css_class'],
        'accent_bar_class': category.get('accent_bar_class', 'bg-indigo-500'),
        'formulation': formulation,
        'page_url': feedback.page_url,
        'page_title': page_title,
        'vote_opened_at': feedback.vote_opened_at,
    }


def build_page_feedback_vote_requests_context(user, *, limit: int = VOTE_REQUESTS_LIMIT) -> dict[str, Any]:
    """Demandes de vote ouvertes affichées sur la page d'accueil."""
    if not user or not getattr(user, 'is_authenticated', False):
        return {
            'show_page_feedback_vote_requests': False,
            'page_feedback_vote_requests': [],
        }

    from feedback.roles import get_available_vote_roles as get_available_nav_profiles

    user_profiles = set(get_available_nav_profiles(user))
    if not user_profiles:
        return {
            'show_page_feedback_vote_requests': False,
            'page_feedback_vote_requests': [],
        }

    voted_ids = set(PageFeedbackVote.objects.filter(user=user).values_list('feedback_id', flat=True))
    candidates = (
        PageFeedback.objects.filter(
            category__in=VOTABLE_FEEDBACK_CATEGORIES,
            vote_opened_at__isnull=False,
            vote_closed_at__isnull=True,
        )
        .exclude(pk__in=voted_ids)
        .order_by('-vote_opened_at')[: limit * 3]
    )
    items = []
    for feedback in candidates:
        vote_roles = set(feedback.vote_roles or [])
        if not (user_profiles & vote_roles):
            continue
        items.append(_vote_request_row(feedback))
        if len(items) >= limit:
            break

    return {
        'show_page_feedback_vote_requests': bool(items),
        'page_feedback_vote_requests': items,
    }


def build_page_feedback_author_responses_context(user, *, limit: int = AUTHOR_RESPONSES_LIMIT) -> dict[str, Any]:
    qs = PageFeedback.objects.filter(
        author=user,
        author_notified_at__isnull=False,
        author_response_seen_at__isnull=True,
    ).order_by('-author_notified_at')[:limit]
    items = [_author_response_row(fb) for fb in qs]
    return {
        'show_page_feedback_responses': bool(items),
        'page_feedback_responses': items,
    }


def build_page_feedback_admin_context(
    *,
    sort: str | None = None,
    view: str | None = None,
    focus_feedback_id: int | None = None,
    limit: int = DASHBOARD_FEEDBACK_LIMIT,
) -> dict[str, Any]:
    view, sort, feedback_rows = feedback_rows_for_admin_view(view=view, sort=sort, limit=limit)
    focus_item_id = parse_feedback_focus(str(focus_feedback_id)) if focus_feedback_id is not None else None
    visible_ids = {feedback.id for feedback in feedback_rows}
    if focus_item_id not in visible_ids:
        focus_item_id = None
    items = []
    for feedback in feedback_rows:
        row = _feedback_row(feedback)
        row['open_on_load'] = focus_item_id is not None and feedback.id == focus_item_id
        items.append(row)
    now = timezone.now()
    unread_count = exclude_active_snoozes(
        PageFeedback.objects.filter(
            status=PageFeedback.STATUS_NEW,
            admin_priority__isnull=True,
            treated_at__isnull=True,
            in_progress_at__isnull=True,
        ),
        now=now,
    ).count()
    treated_count = PageFeedback.objects.filter(treated_at__isnull=False).count()
    in_progress_count = exclude_active_snoozes(
        PageFeedback.objects.filter(in_progress_at__isnull=False, treated_at__isnull=True),
        now=now,
    ).count()
    snoozed_count = PageFeedback.objects.filter(
        active_snoozed_feedback_filter(now=now), treated_at__isnull=True
    ).count()
    pending_count = exclude_active_snoozes(
        PageFeedback.objects.filter(treated_at__isnull=True, in_progress_at__isnull=True),
        now=now,
    ).count()
    default_collapsed = view == FEEDBACK_VIEW_PENDING and pending_count > PENDING_FEEDBACK_COLLAPSE_THRESHOLD
    focus_dom_id = page_feedback_dom_id(focus_item_id) if focus_item_id else ''
    return {
        'show_page_feedback_admin': True,
        'page_feedback_items': items,
        'page_feedback_focus_item_id': focus_item_id,
        'page_feedback_focus_id': focus_dom_id,
        'focus_section_id': focus_dom_id,
        'show_focus_section_scroll': bool(focus_dom_id),
        'page_feedback_unread_count': unread_count,
        'page_feedback_sort': sort,
        'page_feedback_sort_choices': FEEDBACK_SORT_CHOICES,
        'page_feedback_view': view,
        'page_feedback_show_treated': view == FEEDBACK_VIEW_TREATED,
        'page_feedback_show_in_progress': view == FEEDBACK_VIEW_IN_PROGRESS,
        'page_feedback_show_snoozed': view == FEEDBACK_VIEW_SNOOZED,
        'page_feedback_treated_count': treated_count,
        'page_feedback_in_progress_count': in_progress_count,
        'page_feedback_snoozed_count': snoozed_count,
        'page_feedback_pending_count': pending_count,
        'page_feedback_default_collapsed': default_collapsed,
        'page_feedback_pending_list_url': dashboard_feedback_redirect_url(sort, FEEDBACK_VIEW_PENDING),
        'page_feedback_in_progress_list_url': dashboard_feedback_redirect_url(sort, FEEDBACK_VIEW_IN_PROGRESS),
        'page_feedback_snoozed_list_url': dashboard_feedback_redirect_url(sort, FEEDBACK_VIEW_SNOOZED),
        'page_feedback_treated_list_url': dashboard_feedback_redirect_url(sort, FEEDBACK_VIEW_TREATED),
    }


def create_page_feedback(
    *,
    author,
    category: str,
    message: str,
    page_url: str,
    importance: int | None = None,
    page_title: str = '',
    page_context: str = '',
) -> PageFeedback:
    feedback = PageFeedback.objects.create(
        author=author,
        category=category,
        importance=None,
        message=message.strip(),
        page_url=page_url[:500],
        page_title=(page_title or '')[:200],
        page_context=(page_context or '')[:PAGE_CONTEXT_MAX_LENGTH],
    )
    if importance is not None:
        PageFeedbackRating.objects.create(
            feedback=feedback,
            user=author,
            importance=importance,
        )
        recompute_feedback_importance(feedback)
    return feedback


def mark_page_feedback_read(feedback_id: int, reader) -> bool:
    updated = PageFeedback.objects.filter(
        pk=feedback_id,
        status=PageFeedback.STATUS_NEW,
    ).update(
        status=PageFeedback.STATUS_READ,
        read_at=timezone.now(),
        read_by=reader,
    )
    return updated > 0


def set_page_feedback_admin_priority(
    feedback_id: int,
    priority: int | None,
    *,
    reader=None,
) -> bool:
    if priority is not None and priority not in dict(PageFeedback.ADMIN_PRIORITY_CHOICES):
        return False

    feedback = PageFeedback.objects.filter(pk=feedback_id).first()
    if feedback is None:
        return False

    feedback.admin_priority = priority
    update_fields = ['admin_priority']
    if priority is not None and feedback.status == PageFeedback.STATUS_NEW and reader is not None:
        now = timezone.now()
        feedback.status = PageFeedback.STATUS_READ
        feedback.read_at = now
        feedback.read_by = reader
        update_fields.extend(['status', 'read_at', 'read_by'])
    feedback.save(update_fields=update_fields)
    return True


def _clear_page_feedback_snooze(feedback: PageFeedback) -> None:
    feedback.snoozed_until = None
    feedback.snoozed_at = None
    feedback.snoozed_by = None


def set_page_feedback_snoozed(
    feedback_id: int,
    *,
    snoozed_until: datetime,
    admin,
) -> bool:
    """Reporte un retour à une date ultérieure (masqué des listes actives jusqu'à cette date)."""
    feedback = PageFeedback.objects.filter(pk=feedback_id, treated_at__isnull=True).first()
    if feedback is None:
        return False

    now = timezone.now()
    if snoozed_until <= now:
        return False

    feedback.snoozed_until = snoozed_until
    feedback.snoozed_at = now
    feedback.snoozed_by = admin
    update_fields = ['snoozed_until', 'snoozed_at', 'snoozed_by']
    if feedback.status == PageFeedback.STATUS_NEW:
        feedback.status = PageFeedback.STATUS_READ
        feedback.read_at = now
        feedback.read_by = admin
        update_fields.extend(['status', 'read_at', 'read_by'])
    feedback.save(update_fields=update_fields)
    return True


def clear_page_feedback_snooze(feedback_id: int) -> bool:
    """Annule le report et remet le retour dans la liste active."""
    feedback = PageFeedback.objects.filter(pk=feedback_id, treated_at__isnull=True).first()
    if feedback is None or not feedback_is_snoozed(feedback):
        return False

    _clear_page_feedback_snooze(feedback)
    feedback.save(update_fields=['snoozed_until', 'snoozed_at', 'snoozed_by'])
    return True


def set_page_feedback_treated(feedback_id: int, *, treated: bool, admin) -> bool:
    """Marque ou démarque un retour comme traité par l'administrateur."""
    feedback = PageFeedback.objects.filter(pk=feedback_id).first()
    if feedback is None:
        return False

    if treated:
        if feedback.treated_at is not None:
            return True
        now = timezone.now()
        feedback.treated_at = now
        feedback.treated_by = admin
        feedback.in_progress_at = None
        feedback.in_progress_by = None
        _clear_page_feedback_snooze(feedback)
        if feedback.status == PageFeedback.STATUS_NEW:
            feedback.status = PageFeedback.STATUS_READ
            feedback.read_at = now
            feedback.read_by = admin
        feedback.save(
            update_fields=[
                'treated_at',
                'treated_by',
                'in_progress_at',
                'in_progress_by',
                'snoozed_until',
                'snoozed_at',
                'snoozed_by',
                'status',
                'read_at',
                'read_by',
            ]
        )
    else:
        if feedback.treated_at is None:
            return True
        feedback.treated_at = None
        feedback.treated_by = None
        feedback.save(update_fields=['treated_at', 'treated_by'])
    return True


def set_page_feedback_in_progress(feedback_id: int, *, in_progress: bool, admin) -> bool:
    """Marque ou démarque un retour comme en cours de traitement par l'administrateur."""
    feedback = PageFeedback.objects.filter(pk=feedback_id).first()
    if feedback is None:
        return False

    if in_progress:
        if feedback.in_progress_at is not None:
            return True
        now = timezone.now()
        feedback.in_progress_at = now
        feedback.in_progress_by = admin
        feedback.treated_at = None
        feedback.treated_by = None
        _clear_page_feedback_snooze(feedback)
        if feedback.status == PageFeedback.STATUS_NEW:
            feedback.status = PageFeedback.STATUS_READ
            feedback.read_at = now
            feedback.read_by = admin
        feedback.save(
            update_fields=[
                'in_progress_at',
                'in_progress_by',
                'treated_at',
                'treated_by',
                'snoozed_until',
                'snoozed_at',
                'snoozed_by',
                'status',
                'read_at',
                'read_by',
            ]
        )
    else:
        if feedback.in_progress_at is None:
            return True
        feedback.in_progress_at = None
        feedback.in_progress_by = None
        feedback.save(update_fields=['in_progress_at', 'in_progress_by'])
    return True


def notify_page_feedback_author(feedback_id: int, notifier) -> bool:
    """Marque le retour comme traité et affiche une réponse sur l'accueil de l'auteur."""
    feedback = PageFeedback.objects.filter(pk=feedback_id).first()
    if feedback is None or feedback.author_notified_at is not None:
        return False

    now = timezone.now()
    feedback.author_notified_at = now
    feedback.author_notified_by = notifier
    if feedback.treated_at is None:
        feedback.treated_at = now
        feedback.treated_by = notifier
        feedback.in_progress_at = None
        feedback.in_progress_by = None
    if feedback.status == PageFeedback.STATUS_NEW:
        feedback.status = PageFeedback.STATUS_READ
        feedback.read_at = now
        feedback.read_by = notifier
    feedback.save(
        update_fields=[
            'author_notified_at',
            'author_notified_by',
            'treated_at',
            'treated_by',
            'in_progress_at',
            'in_progress_by',
            'status',
            'read_at',
            'read_by',
        ]
    )
    return True


def dismiss_page_feedback_response(feedback_id: int, user) -> bool:
    """L'auteur masque la réponse affichée sur son accueil."""
    updated = PageFeedback.objects.filter(
        pk=feedback_id,
        author=user,
        author_notified_at__isnull=False,
        author_response_seen_at__isnull=True,
    ).update(author_response_seen_at=timezone.now())
    return updated > 0


def _current_vote_formulation(feedback: PageFeedback) -> str:
    if feedback.vote_formulation:
        return feedback.vote_formulation.strip()
    return feedback.message.strip()


def open_feedback_vote(
    *,
    feedback_id: int,
    formulation: str,
    roles: list[str],
    admin,
) -> PageFeedback | None:
    """Reformule si besoin, ouvre le vote et cible les rôles sélectionnés."""
    from feedback.roles import VOTE_ROLE_LABELS as NAV_PROFILE_LABELS

    valid_roles = {key for key in NAV_PROFILE_LABELS}
    roles = [role for role in roles if role in valid_roles]
    formulation = formulation.strip()
    if not roles or len(formulation) < 10:
        return None

    feedback = PageFeedback.objects.filter(pk=feedback_id).first()
    if feedback is None or not feedback_is_votable_category(feedback.category):
        return None

    previous_formulation = _current_vote_formulation(feedback)
    if previous_formulation != formulation:
        feedback.votes.all().delete()

    now = timezone.now()
    feedback.vote_formulation = formulation
    feedback.vote_roles = roles
    feedback.vote_opened_at = now
    feedback.vote_opened_by = admin
    feedback.vote_closed_at = None
    feedback.vote_closed_by = None
    update_fields = [
        'vote_formulation',
        'vote_roles',
        'vote_opened_at',
        'vote_opened_by',
        'vote_closed_at',
        'vote_closed_by',
    ]
    if feedback.status == PageFeedback.STATUS_NEW:
        feedback.status = PageFeedback.STATUS_READ
        feedback.read_at = now
        feedback.read_by = admin
        update_fields.extend(['status', 'read_at', 'read_by'])
    feedback.save(update_fields=update_fields)
    return feedback


def close_feedback_vote(feedback_id: int, admin) -> bool:
    """Clôture le vote sans autre effet ; peut être rouvert ensuite."""
    feedback = PageFeedback.objects.filter(pk=feedback_id).first()
    if feedback is None or not feedback_vote_is_open(feedback):
        return False

    now = timezone.now()
    feedback.vote_closed_at = now
    feedback.vote_closed_by = admin
    feedback.save(update_fields=['vote_closed_at', 'vote_closed_by'])
    return True


def reopen_feedback_vote(feedback_id: int, admin) -> bool:
    """Rouvre un vote précédemment clos (les votes existants sont conservés)."""
    feedback = PageFeedback.objects.filter(pk=feedback_id).first()
    if feedback is None or feedback.vote_opened_at is None or feedback.vote_closed_at is None:
        return False

    feedback.vote_closed_at = None
    feedback.vote_closed_by = None
    feedback.save(update_fields=['vote_closed_at', 'vote_closed_by'])
    return True


def submit_feedback_vote(
    *,
    feedback_id: int,
    user,
    choice: str,
) -> PageFeedback | None:
    """Enregistre le vote pour/contre d'un utilisateur éligible."""
    if choice not in (PageFeedbackVote.VOTE_FOR, PageFeedbackVote.VOTE_AGAINST):
        return None

    feedback = PageFeedback.objects.filter(pk=feedback_id).first()
    if feedback is None or not user_can_participate_in_feedback_vote(user, feedback):
        return None
    if feedback.votes.filter(user=user).exists():
        return None

    PageFeedbackVote.objects.create(
        feedback=feedback,
        user=user,
        choice=choice,
    )
    return feedback
