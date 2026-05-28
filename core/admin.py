from django.contrib import admin
from .models import ExternalLink, MediaItem

@admin.register(ExternalLink)
class ExternalLinkAdmin(admin.ModelAdmin):
    list_display = ("label", "slug", "url", "actif")

@admin.register(MediaItem)
class MediaItemAdmin(admin.ModelAdmin):
    list_display = ("titre", "type", "ordre", "publie")
    list_editable = ("ordre", "publie")
