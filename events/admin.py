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
    list_display   = ("date_debut", "titre", "type", "venue", "statut", "public")
    list_editable  = ("statut", "public")
    list_filter    = ("statut", "type", "public")
    search_fields  = ("titre", "venue__nom", "venue__ville")
    date_hierarchy = "date_debut"
    ordering       = ("date_debut",)
    fields         = ("titre", "type", "venue", "date_debut", "date_fin",
                      "statut", "public", "url_billets", "description")
