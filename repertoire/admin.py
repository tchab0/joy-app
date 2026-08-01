from django.contrib import admin

from repertoire.models import Part, Piece, Setlist, SetlistItem


class PartInline(admin.TabularInline):
    model = Part
    extra = 0


@admin.register(Piece)
class PieceAdmin(admin.ModelAdmin):
    list_display = ("title", "is_published", "has_audio", "updated_at")
    list_filter = ("is_published",)
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [PartInline]
    fieldsets = (
        (None, {"fields": ("title", "slug", "is_published")}),
        ("Notes", {"fields": ("remarks", "chorus_order", "chorus_order_updated_at")}),
        (
            "Écoute",
            {"fields": ("youtube_url_1", "youtube_url_2", "youtube_url_3", "audio_recording")},
        ),
    )
    readonly_fields = ("chorus_order_updated_at",)

    @admin.display(boolean=True, description="Audio")
    def has_audio(self, obj: Piece) -> bool:
        return bool(obj.audio_recording)


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ("piece", "poste", "source_name", "updated_at")
    list_filter = ("poste",)
    search_fields = ("piece__title", "source_name")
    autocomplete_fields = ("piece",)


class SetlistItemInline(admin.TabularInline):
    model = SetlistItem
    extra = 0
    autocomplete_fields = ("piece",)


@admin.register(Setlist)
class SetlistAdmin(admin.ModelAdmin):
    list_display = ("title", "event", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("title",)
    autocomplete_fields = ("event", "created_by")
    inlines = [SetlistItemInline]
