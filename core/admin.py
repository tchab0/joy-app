from django.contrib import admin
from .models import ExternalLink, EvenementMedia, MediaItem, MediaVote, ContactMessage


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
    list_display = ("titre", "type", "statut", "publie", "soumis_par_nom", "soumis_le")
    list_filter = ("type", "statut", "publie")
    search_fields = ("titre", "soumis_par_nom", "soumis_par_email")
    autocomplete_fields = ("evenement",)


@admin.register(MediaVote)
class MediaVoteAdmin(admin.ModelAdmin):
    list_display = ("media", "session_key", "created_at")
    search_fields = ("session_key",)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "nom", "email", "telephone", "statut")
    list_filter = ("statut", "created_at")
    search_fields = ("nom", "email", "telephone", "message")
    readonly_fields = ("created_at", "processed_at")
