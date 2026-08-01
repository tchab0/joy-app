from django.urls import path

from . import views

urlpatterns = [
    path("admin-retours/", views.admin_feedback, name="admin_feedback"),
    path("feedback/pending/", views.pending_page_feedback, name="pending_page_feedback"),
    path("feedback/submit/", views.submit_page_feedback, name="submit_page_feedback"),
    path("feedback/<int:feedback_id>/read/", views.mark_page_feedback_read_view, name="mark_page_feedback_read"),
    path(
        "feedback/<int:feedback_id>/priority/",
        views.set_page_feedback_priority_view,
        name="set_page_feedback_priority",
    ),
    path(
        "feedback/<int:feedback_id>/treated/",
        views.set_page_feedback_treated_view,
        name="set_page_feedback_treated",
    ),
    path(
        "feedback/<int:feedback_id>/in-progress/",
        views.set_page_feedback_in_progress_view,
        name="set_page_feedback_in_progress",
    ),
    path(
        "feedback/<int:feedback_id>/snooze/",
        views.set_page_feedback_snooze_view,
        name="set_page_feedback_snooze",
    ),
    path(
        "feedback/<int:feedback_id>/unsnooze/",
        views.clear_page_feedback_snooze_view,
        name="clear_page_feedback_snooze",
    ),
    path(
        "feedback/<int:feedback_id>/notify/",
        views.notify_page_feedback_author_view,
        name="notify_page_feedback_author",
    ),
    path(
        "feedback/<int:feedback_id>/dismiss/",
        views.dismiss_page_feedback_response_view,
        name="dismiss_page_feedback_response",
    ),
    path(
        "feedback/<int:feedback_id>/vote/open/",
        views.open_page_feedback_vote_view,
        name="open_page_feedback_vote",
    ),
    path(
        "feedback/<int:feedback_id>/vote/close/",
        views.close_page_feedback_vote_view,
        name="close_page_feedback_vote",
    ),
    path(
        "feedback/<int:feedback_id>/vote/reopen/",
        views.reopen_page_feedback_vote_view,
        name="reopen_page_feedback_vote",
    ),
    path(
        "feedback/<int:feedback_id>/vote/",
        views.submit_page_feedback_vote_view,
        name="submit_page_feedback_vote",
    ),
]
