from django.contrib import admin
from .models import Venue, EventType, Event


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display  = ("nom", "ville")
    search_fields = ("nom", "ville")


@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    pass


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display   = ("date_debut", "titre", "slug", "type", "venue", "organisme", "statut", "public")
    list_editable  = ("statut", "public")
    list_filter    = ("statut", "type", "public")
    search_fields  = ("titre", "slug", "venue__nom", "venue__ville", "organisme")
    autocomplete_fields = ("parent", "venue")
    prepopulated_fields = {"slug": ("titre",)}
    date_hierarchy = "date_debut"
    ordering       = ("date_debut",)
    fields         = (
        "titre", "slug", "type", "venue", "date_debut", "date_fin",
        "statut", "public", "parent", "organisme", "url_billets",
        "contact_nom", "contact_telephone", "contact_email",
        "description",
    )
