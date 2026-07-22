from django.contrib import admin

from planning.models import (
    DateOption,
    DateProposal,
    DateVote,
    EquipmentItem,
    EventEquipmentAssignment,
    EventParticipation,
    MusicianProfile,
    OrchestraSection,
    ParticipationStatus,
    SubstituteRequest,
)


@admin.register(ParticipationStatus)
class ParticipationStatusAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "color_token", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("code", "label")
    prepopulated_fields = {"code": ("label",)}


@admin.register(OrchestraSection)
class OrchestraSectionAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("name", "code")
    prepopulated_fields = {"code": ("name",)}


@admin.register(MusicianProfile)
class MusicianProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "section",
        "poste_titulaire",
        "poste_remplacant",
        "poste_remplacant_2",
        "poste_remplacant_3",
        "poste_remplacant_4",
        "poste_remplacant_5",
    )
    list_filter = (
        "section",
        "poste_titulaire",
        "poste_remplacant",
        "poste_remplacant_2",
        "poste_remplacant_3",
        "poste_remplacant_4",
        "poste_remplacant_5",
    )
    list_editable = (
        "poste_titulaire",
        "poste_remplacant",
        "poste_remplacant_2",
        "poste_remplacant_3",
        "poste_remplacant_4",
        "poste_remplacant_5",
    )
    search_fields = ("user__username", "user__first_name", "user__last_name")
    autocomplete_fields = ("user", "section")


@admin.register(EventParticipation)
class EventParticipationAdmin(admin.ModelAdmin):
    list_display = ("event", "user", "poste", "role_kind", "status", "updated_at")
    list_filter = ("status", "role_kind", "poste")
    search_fields = ("user__username", "user__first_name", "user__last_name", "event__titre")
    autocomplete_fields = ("event", "user", "status")


class DateOptionInline(admin.TabularInline):
    model = DateOption
    extra = 1


@admin.register(DateOption)
class DateOptionAdmin(admin.ModelAdmin):
    list_display = ("proposal", "starts_at", "label", "sort_order")
    search_fields = ("label", "proposal__title")


@admin.register(DateProposal)
class DateProposalAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "created_by", "created_at", "linked_event")
    list_filter = ("status",)
    inlines = [DateOptionInline]
    autocomplete_fields = ("created_by", "linked_event")
    raw_id_fields = ("locked_option",)

@admin.register(DateVote)
class DateVoteAdmin(admin.ModelAdmin):
    list_display = ("option", "user", "choice", "updated_at")
    list_filter = ("choice",)


@admin.register(SubstituteRequest)
class SubstituteRequestAdmin(admin.ModelAdmin):
    list_display = ("participation", "candidate", "status", "created_at")
    list_filter = ("status",)


@admin.register(EquipmentItem)
class EquipmentItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")


@admin.register(EventEquipmentAssignment)
class EventEquipmentAssignmentAdmin(admin.ModelAdmin):
    list_display = ("event", "item", "assigned_to", "status")
    list_filter = ("status",)
