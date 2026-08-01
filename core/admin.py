from django.contrib import admin
from .models import (
    ExternalLink,
    EvenementMedia,
    MediaItem,
    MediaVote,
    ContactMessage,
    SitePage,
    PageBlock,
)


@admin.register(ExternalLink)
class ExternalLinkAdmin(admin.ModelAdmin):
    list_display = ("titre", "slug", "url", "actif")
    list_filter = ("actif",)
    search_fields = ("titre", "slug", "url")


@admin.register(EvenementMedia)
class EvenementMediaAdmin(admin.ModelAdmin):
    list_display = ("nom", "date", "lieu")
    search_fields = ("nom", "lieu")
    list_filter = ("date",)


@admin.register(MediaItem)
class MediaItemAdmin(admin.ModelAdmin):
    list_display = ("titre", "type", "statut", "publie", "soumis_par_nom", "soumis_le", "edite_le")
    list_filter = ("type", "statut", "publie")
    search_fields = ("titre", "soumis_par_nom", "soumis_par_email")
    autocomplete_fields = ("evenement",)
    readonly_fields = ("edite_le",)


@admin.register(MediaVote)
class MediaVoteAdmin(admin.ModelAdmin):
    list_display = ("media", "session_key", "created_at")
    search_fields = ("session_key",)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "nom", "email", "telephone", "ville", "statut")
    list_filter = ("kind", "statut", "created_at", "budget", "type_evenement")
    search_fields = ("nom", "email", "telephone", "message", "ville", "organisation")
    readonly_fields = ("created_at", "processed_at")


class PageBlockInline(admin.TabularInline):
    model = PageBlock
    extra = 0
    fields = ("type", "titre_admin", "ordre", "visible", "media")
    ordering = ("ordre", "id")


@admin.register(SitePage)
class SitePageAdmin(admin.ModelAdmin):
    list_display = ("titre", "slug", "publie", "updated_at")
    list_filter = ("publie",)
    search_fields = ("titre", "slug")
    prepopulated_fields = {"slug": ("titre",)}
    inlines = [PageBlockInline]


@admin.register(PageBlock)
class PageBlockAdmin(admin.ModelAdmin):
    list_display = ("page", "type", "titre_admin", "ordre", "visible")
    list_filter = ("type", "visible", "page")
    search_fields = ("titre_admin", "page__slug")
    autocomplete_fields = ("media", "page")
