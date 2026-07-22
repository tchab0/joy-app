from django.contrib import admin

from stats.models import PublicPageView, UsageEvent


@admin.register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "path", "created_at")
    list_filter = ("name",)
    search_fields = ("path", "user__username", "user__email", "user__last_name")
    readonly_fields = ("user", "name", "path", "created_at")
    date_hierarchy = "created_at"


@admin.register(PublicPageView)
class PublicPageViewAdmin(admin.ModelAdmin):
    list_display = ("path", "session_key", "created_at")
    search_fields = ("path", "session_key")
    readonly_fields = ("path", "session_key", "created_at")
    date_hierarchy = "created_at"
