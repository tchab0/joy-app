from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import AuthChallenge, User
from .roles import sync_user_groups


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
