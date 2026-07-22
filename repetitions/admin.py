from django.contrib import admin

from repetitions.models import RehearsalItem, RehearsalPlan


class RehearsalItemInline(admin.TabularInline):
    model = RehearsalItem
    extra = 0
    autocomplete_fields = ("piece",)


@admin.register(RehearsalPlan)
class RehearsalPlanAdmin(admin.ModelAdmin):
    list_display = ("event", "updated_at", "updated_by")
    search_fields = ("event__titre", "notes")
    raw_id_fields = ("event", "updated_by")
    inlines = [RehearsalItemInline]
