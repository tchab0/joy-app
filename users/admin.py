from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import AuthChallenge, ProductTour, ProductTourStep, PushSubscription, User
from .roles import sync_user_groups


class ProductTourStepInline(admin.TabularInline):
    model = ProductTourStep
    extra = 0
    ordering = ("order", "pk")
    fields = (
        "order",
        "anchor",
        "title",
        "body",
        "page_path",
        "open_mobile_nav",
        "scroll_footer",
        "is_active",
    )


@admin.register(ProductTour)
class ProductTourAdmin(admin.ModelAdmin):
    list_display = ("title", "audience", "version", "is_active", "steps_count")
    list_filter = ("audience", "is_active")
    search_fields = ("title",)
    inlines = [ProductTourStepInline]
    fieldsets = (
        (
            None,
            {
                "fields": ("audience", "title", "version", "is_active"),
                "description": (
                    "Modifiez le texte et l’ordre des étapes ci-dessous. "
                    "Ancres disponibles : nav-planning, nav-repertoire, nav-chat, "
                    "nav-account, module-calendrier, module-mes-dates, module-staff, "
                    "rsvp-actions, repertoire-filter, chat-list, staff-admin, "
                    "staff-musiciens, staff-atelier, footer-admin, account-replay. "
                    "Incrémentez la version pour re-proposer le guide."
                ),
            },
        ),
    )

    @admin.display(description="Étapes")
    def steps_count(self, obj):
        return obj.steps.count()


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "endpoint_short", "created_at", "updated_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "user__email", "endpoint")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Endpoint")
    def endpoint_short(self, obj):
        return (obj.endpoint or "")[:64]


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "username",
        "email",
        "phone",
        "is_musician",
        "is_association_member",
        "membership_expires_at",
        "two_factor_enabled",
        "totp_enabled",
        "is_staff",
        "is_active",
    )
    list_filter = (
        "is_musician",
        "is_association_member",
        "two_factor_enabled",
        "totp_enabled",
        "is_staff",
        "is_active",
        "email_verified",
        "phone_verified",
    )
    search_fields = ("username", "email", "phone", "first_name", "last_name")
    ordering = ("last_name", "first_name", "username")

    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Profil JOY",
            {
                "fields": (
                    "phone",
                    "phone_verified",
                    "email_verified",
                    "is_musician",
                    "is_association_member",
                    "membership_expires_at",
                )
            },
        ),
        (
            "Guides (coach marks)",
            {
                "fields": (
                    "tour_musician_version",
                    "tour_staff_version",
                    "dismissed_page_leads",
                ),
                "description": (
                    "Remettre à 0 pour re-proposer automatiquement le guide "
                    "à la prochaine connexion. Vider dismissed_page_leads "
                    "pour réafficher les aides de page."
                ),
            },
        ),
        (
            "Double authentification",
            {
                "fields": (
                    "two_factor_enabled",
                    "preferred_2fa_channel",
                    "totp_enabled",
                    "totp_secret",
                )
            },
        ),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "Profil JOY",
            {
                "fields": (
                    "email",
                    "phone",
                    "is_musician",
                    "is_association_member",
                    "membership_expires_at",
                )
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        sync_user_groups(obj)
        if obj.is_musician:
            from planning.services import get_or_create_profile

            get_or_create_profile(obj)


@admin.register(AuthChallenge)
class AuthChallengeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "purpose",
        "channel",
        "destination",
        "created_at",
        "expires_at",
        "consumed_at",
        "attempts",
    )
    list_filter = ("purpose", "channel")
    search_fields = ("user__username", "user__email", "destination")
    readonly_fields = (
        "id",
        "user",
        "purpose",
        "channel",
        "code_hash",
        "destination",
        "created_at",
        "expires_at",
        "consumed_at",
        "attempts",
        "max_attempts",
        "session_key",
    )
