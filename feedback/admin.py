from django.contrib import admin

from .models import PageFeedback, PageFeedbackMessage, PageFeedbackRating, PageFeedbackVote


class PageFeedbackMessageInline(admin.TabularInline):
    model = PageFeedbackMessage
    extra = 0
    readonly_fields = ("sender", "body", "is_from_staff", "created_at")
    can_delete = False


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
        "has_attachment",
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
    inlines = (PageFeedbackMessageInline,)

    @admin.display(boolean=True, description="PJ")
    def has_attachment(self, obj):
        return bool(obj.attachment)


@admin.register(PageFeedbackRating)
class PageFeedbackRatingAdmin(admin.ModelAdmin):
    list_display = ("created_at", "feedback", "user", "importance")
    list_filter = ("importance",)


@admin.register(PageFeedbackVote)
class PageFeedbackVoteAdmin(admin.ModelAdmin):
    list_display = ("created_at", "feedback", "user", "choice")
    list_filter = ("choice",)


@admin.register(PageFeedbackMessage)
class PageFeedbackMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "feedback", "sender", "is_from_staff")
    list_filter = ("is_from_staff",)
    search_fields = ("body", "sender__username", "sender__email")
    readonly_fields = ("created_at",)
