from django.contrib import admin
from .models import Venue, EventType, Event, Organisme


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display  = ("nom", "ville")
    search_fields = ("nom", "ville")


@admin.register(Organisme)
class OrganismeAdmin(admin.ModelAdmin):
    list_display = ("nom",)
    search_fields = ("nom",)


@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    list_display = ("nom", "is_rehearsal")
    list_editable = ("is_rehearsal",)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display   = (
        "date_debut", "titre", "slug", "type", "venue", "organisme",
        "statut", "public", "shares_facebook", "shares_instagram", "shares_bluesky",
    )
    list_editable  = ("statut", "public")
    list_filter    = ("statut", "type", "public")
    search_fields  = ("titre", "slug", "venue__nom", "venue__ville", "organisme")
    autocomplete_fields = ("parent", "venue")
    prepopulated_fields = {"slug": ("titre",)}
    date_hierarchy = "date_debut"
    ordering       = ("date_debut",)
    readonly_fields = ("shares_facebook", "shares_instagram", "shares_bluesky")
    fields         = (
        "titre", "slug", "type", "venue", "date_debut", "date_fin",
        "statut", "public", "parent", "organisme", "url_billets",
        "contact_nom", "contact_telephone", "contact_email",
        "description",
        "shares_facebook", "shares_instagram", "shares_bluesky",
    )
