from django.contrib import admin
from .models import Lieu, Concert

@admin.register(Lieu)
class LieuAdmin(admin.ModelAdmin):
    list_display  = ('nom', 'ville')
    search_fields = ('nom', 'ville')


@admin.register(Concert)
class ConcertAdmin(admin.ModelAdmin):
    list_display   = ('date', 'titre', 'lieu', 'statut', 'public')
    list_editable  = ('statut', 'public')
    list_filter    = ('statut', 'public')
    search_fields  = ('titre', 'lieu__nom', 'lieu__ville')
    date_hierarchy = 'date'
    ordering       = ('date',)
