from __future__ import annotations

from urllib.parse import urlparse

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from feedback.forms import PageFeedbackForm, PageFeedbackVoteOpenForm
from feedback.services.page_feedback import (
    FEEDBACK_VIEW_PENDING,
    build_page_feedback_admin_context,
    build_page_feedback_author_responses_context,
    build_page_feedback_vote_requests_context,
    build_pending_page_feedback_items,
    can_manage_page_feedback,
    clear_page_feedback_snooze,
    close_feedback_vote,
    create_page_feedback,
    dismiss_page_feedback_response,
    mark_page_feedback_read,
    notify_page_feedback_author,
    open_feedback_vote,
    parse_feedback_focus,
    parse_snooze_until_date,
    rate_page_feedback,
    redirect_url_after_feedback_admin_action,
    reopen_feedback_vote,
    resolve_feedback_page_info,
    set_page_feedback_admin_priority,
    set_page_feedback_in_progress,
    set_page_feedback_snoozed,
    set_page_feedback_treated,
    submit_feedback_vote,
)
from feedback.models import PageFeedbackVote


def _admin_denied():
    return HttpResponseForbidden("Action réservée aux administrateurs.")


@staff_member_required
def admin_feedback(request):
    context = build_page_feedback_admin_context(
        sort=request.GET.get("feedback_sort"),
        view=request.GET.get("feedback_view"),
        focus_feedback_id=parse_feedback_focus(request.GET.get("feedback_focus")),
    )
    context.update(build_page_feedback_author_responses_context(request.user))
    context.update(build_page_feedback_vote_requests_context(request.user))
    return render(request, "feedback/admin_feedback.html", context)


@login_required
@require_GET
def pending_page_feedback(request):
    page_url = (request.GET.get("page_url") or "").strip() or request.get_full_path()
    category = (request.GET.get("category") or "").strip() or None
    items = build_pending_page_feedback_items(
        page_url=page_url,
        category=category,
        user=request.user,
    )
    return JsonResponse({"items": items})


@login_required
@require_POST
def submit_page_feedback(request):
    data = request.POST.copy()
    page_url = (data.get("page_url") or "").strip()
    if not page_url:
        referer = request.META.get("HTTP_REFERER", "")
        page_url = urlparse(referer).path if referer else reverse("home")
        data["page_url"] = page_url or reverse("home")

    form = PageFeedbackForm(data)
    redirect_to = (data.get("page_url") or reverse("home")).strip()
    if not redirect_to.startswith("/"):
        redirect_to = reverse("home")

    if form.is_valid():
        page_info = resolve_feedback_page_info(request, data)
        existing_id = form.cleaned_data.get("existing_feedback_id")
        importance = form.cleaned_data["importance"]

        if existing_id:
            feedback = rate_page_feedback(
                feedback_id=existing_id,
                user=request.user,
                importance=importance,
            )
            if feedback is None:
                messages.error(
                    request,
                    "Ce retour n'est plus disponible. Choisissez-en un autre ou rédigez une nouvelle description.",
                )
            else:
                messages.success(
                    request,
                    "Merci, votre soutien a bien été enregistré.",
                )
        else:
            create_page_feedback(
                author=request.user,
                category=form.cleaned_data["category"],
                message=form.cleaned_data["message"],
                importance=importance,
                page_url=page_info["page_url"],
                page_title=page_info["page_title"],
                page_context=page_info["page_context"],
            )
            messages.success(request, "Merci, votre retour a bien été transmis aux administrateurs.")
    else:
        error_messages = [str(error) for errors in form.errors.values() for error in errors]
        detail = error_messages[0] if error_messages else "Vérifiez le formulaire."
        messages.error(request, f"Le retour n'a pas pu être enregistré : {detail}")

    return redirect(redirect_to)


@login_required
@require_POST
def mark_page_feedback_read_view(request, feedback_id):
    if not can_manage_page_feedback(request.user):
        return _admin_denied()
    mark_page_feedback_read(feedback_id, request.user)
    return redirect(
        redirect_url_after_feedback_admin_action(
            acted_feedback_id=feedback_id,
            sort=request.POST.get("feedback_sort"),
            view=request.POST.get("feedback_view") or FEEDBACK_VIEW_PENDING,
            leaves_current_list=False,
        )
    )


@login_required
@require_POST
def set_page_feedback_priority_view(request, feedback_id):
    if not can_manage_page_feedback(request.user):
        return _admin_denied()
    raw = (request.POST.get("admin_priority") or request.POST.get("priority") or "").strip()
    try:
        priority = None if raw in ("", "0") else int(raw)
    except ValueError:
        priority = None
    set_page_feedback_admin_priority(feedback_id, priority, reader=request.user)
    return redirect(
        redirect_url_after_feedback_admin_action(
            acted_feedback_id=feedback_id,
            sort=request.POST.get("feedback_sort"),
            view=request.POST.get("feedback_view") or FEEDBACK_VIEW_PENDING,
            leaves_current_list=False,
        )
    )


@login_required
@require_POST
def set_page_feedback_treated_view(request, feedback_id):
    if not can_manage_page_feedback(request.user):
        return _admin_denied()
    treated = request.POST.get("treated") == "1"
    set_page_feedback_treated(feedback_id, treated=treated, admin=request.user)
    return redirect(
        redirect_url_after_feedback_admin_action(
            acted_feedback_id=feedback_id,
            sort=request.POST.get("feedback_sort"),
            view=request.POST.get("feedback_view") or FEEDBACK_VIEW_PENDING,
            leaves_current_list=True,
        )
    )


@login_required
@require_POST
def set_page_feedback_in_progress_view(request, feedback_id):
    if not can_manage_page_feedback(request.user):
        return _admin_denied()
    in_progress = request.POST.get("in_progress") == "1"
    set_page_feedback_in_progress(feedback_id, in_progress=in_progress, admin=request.user)
    return redirect(
        redirect_url_after_feedback_admin_action(
            acted_feedback_id=feedback_id,
            sort=request.POST.get("feedback_sort"),
            view=request.POST.get("feedback_view") or FEEDBACK_VIEW_PENDING,
            leaves_current_list=True,
        )
    )


@login_required
@require_POST
def set_page_feedback_snooze_view(request, feedback_id):
    if not can_manage_page_feedback(request.user):
        return _admin_denied()
    snoozed_until = parse_snooze_until_date(
        request.POST.get("snoozed_until") or request.POST.get("snooze_until")
    )
    if snoozed_until is None:
        messages.error(request, "Date de report invalide.")
    else:
        set_page_feedback_snoozed(feedback_id, snoozed_until=snoozed_until, admin=request.user)
    return redirect(
        redirect_url_after_feedback_admin_action(
            acted_feedback_id=feedback_id,
            sort=request.POST.get("feedback_sort"),
            view=request.POST.get("feedback_view") or FEEDBACK_VIEW_PENDING,
            leaves_current_list=True,
        )
    )


@login_required
@require_POST
def clear_page_feedback_snooze_view(request, feedback_id):
    if not can_manage_page_feedback(request.user):
        return _admin_denied()
    clear_page_feedback_snooze(feedback_id)
    return redirect(
        redirect_url_after_feedback_admin_action(
            acted_feedback_id=feedback_id,
            sort=request.POST.get("feedback_sort"),
            view=request.POST.get("feedback_view") or FEEDBACK_VIEW_PENDING,
            leaves_current_list=True,
        )
    )


@login_required
@require_POST
def notify_page_feedback_author_view(request, feedback_id):
    if not can_manage_page_feedback(request.user):
        return _admin_denied()
    if notify_page_feedback_author(feedback_id, request.user):
        messages.success(request, "L'auteur sera informé sur sa page Compte.")
    else:
        messages.warning(request, "Ce retour est introuvable ou l'auteur a déjà été informé.")
    return redirect(
        redirect_url_after_feedback_admin_action(
            acted_feedback_id=feedback_id,
            sort=request.POST.get("feedback_sort"),
            view=request.POST.get("feedback_view") or FEEDBACK_VIEW_PENDING,
            leaves_current_list=True,
        )
    )


@login_required
@require_POST
def dismiss_page_feedback_response_view(request, feedback_id):
    if dismiss_page_feedback_response(feedback_id, request.user):
        messages.success(request, "Message masqué.")
    else:
        messages.warning(request, "Ce message est introuvable.")
    return redirect("account_home")


@login_required
@require_POST
def open_page_feedback_vote_view(request, feedback_id):
    if not can_manage_page_feedback(request.user):
        return _admin_denied()
    form = PageFeedbackVoteOpenForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Impossible d'ouvrir le vote : vérifiez la formulation et les rôles.")
    else:
        feedback = open_feedback_vote(
            feedback_id=feedback_id,
            formulation=form.cleaned_data["formulation"],
            roles=form.cleaned_data["vote_roles"],
            admin=request.user,
        )
        if feedback is None:
            messages.error(request, "Impossible d'ouvrir le vote pour ce retour.")
        else:
            messages.success(request, "Vote ouvert.")
    return redirect(
        redirect_url_after_feedback_admin_action(
            acted_feedback_id=feedback_id,
            sort=request.POST.get("feedback_sort"),
            view=request.POST.get("feedback_view") or FEEDBACK_VIEW_PENDING,
            leaves_current_list=False,
        )
    )


@login_required
@require_POST
def close_page_feedback_vote_view(request, feedback_id):
    if not can_manage_page_feedback(request.user):
        return _admin_denied()
    close_feedback_vote(feedback_id, request.user)
    return redirect(
        redirect_url_after_feedback_admin_action(
            acted_feedback_id=feedback_id,
            sort=request.POST.get("feedback_sort"),
            view=request.POST.get("feedback_view") or FEEDBACK_VIEW_PENDING,
            leaves_current_list=False,
        )
    )


@login_required
@require_POST
def reopen_page_feedback_vote_view(request, feedback_id):
    if not can_manage_page_feedback(request.user):
        return _admin_denied()
    reopen_feedback_vote(feedback_id, request.user)
    return redirect(
        redirect_url_after_feedback_admin_action(
            acted_feedback_id=feedback_id,
            sort=request.POST.get("feedback_sort"),
            view=request.POST.get("feedback_view") or FEEDBACK_VIEW_PENDING,
            leaves_current_list=False,
        )
    )


@login_required
@require_POST
def submit_page_feedback_vote_view(request, feedback_id):
    choice = (request.POST.get("choice") or "").strip().upper()
    feedback = submit_feedback_vote(
        feedback_id=feedback_id,
        user=request.user,
        choice=choice,
    )
    if feedback is None:
        messages.error(request, "Vote impossible (non éligible ou déjà voté).")
    else:
        label = "pour" if choice == PageFeedbackVote.VOTE_FOR else "contre"
        messages.success(request, f"Votre vote {label} a été enregistré.")
    return redirect("account_home")
