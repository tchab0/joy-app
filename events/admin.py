from django.contrib import admin
from .models import Venue, EventType, Event

@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("nom", "ville")

@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    pass

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("titre", "type", "venue", "date_debut", "public")
    list_filter = ("type", "public")
    date_hierarchy = "date_debut"
