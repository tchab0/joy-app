from django.contrib import admin

from .models import PageFeedback, PageFeedbackRating, PageFeedbackVote


@admin.register(PageFeedback)
class PageFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "category",
        "importance",
        "admin_priority",
        "author",
        "page_title",
        "page_url",
        "status",
        "treated_at",
        "author_notified_at",
    )
    list_filter = (
        "category",
        "importance",
        "admin_priority",
        "status",
        "created_at",
        "treated_at",
    )
    search_fields = ("message", "page_url", "page_title", "author__username", "author__email")
    readonly_fields = (
        "created_at",
        "read_at",
        "read_by",
        "author_notified_at",
        "author_notified_by",
        "author_response_seen_at",
        "treated_at",
        "treated_by",
        "in_progress_at",
        "in_progress_by",
        "snoozed_until",
        "snoozed_at",
        "snoozed_by",
        "vote_opened_at",
        "vote_opened_by",
        "vote_closed_at",
        "vote_closed_by",
        "importance_score",
    )


@admin.register(PageFeedbackRating)
class PageFeedbackRatingAdmin(admin.ModelAdmin):
    list_display = ("created_at", "feedback", "user", "importance")
    list_filter = ("importance",)


@admin.register(PageFeedbackVote)
class PageFeedbackVoteAdmin(admin.ModelAdmin):
    list_display = ("created_at", "feedback", "user", "choice")
    list_filter = ("choice",)
