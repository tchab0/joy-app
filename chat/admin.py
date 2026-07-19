from django.contrib import admin

from chat.models import ChatAttachment, ChatMembership, ChatMessage, ChatRoom


class ChatAttachmentInline(admin.TabularInline):
    model = ChatAttachment
    extra = 0
    readonly_fields = ("original_name", "content_type", "size", "created_at")


class ChatMembershipInline(admin.TabularInline):
    model = ChatMembership
    extra = 0
    autocomplete_fields = ("user",)
    readonly_fields = ("joined_at",)


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "event", "is_active", "created_at")
    list_filter = ("kind", "is_active")
    search_fields = ("title",)
    inlines = [ChatMembershipInline]


@admin.register(ChatMembership)
class ChatMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "room",
        "subscribed",
        "joined_at",
        "left_at",
        "last_read_at",
    )
    list_filter = ("subscribed", "room__kind")
    search_fields = ("user__username", "user__first_name", "user__last_name", "room__title")
    autocomplete_fields = ("user", "room")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "room", "author", "created_at", "deleted_at")
    list_filter = ("room__kind",)
    search_fields = ("body", "author__username")
    autocomplete_fields = ("author", "room")
    inlines = [ChatAttachmentInline]


@admin.register(ChatAttachment)
class ChatAttachmentAdmin(admin.ModelAdmin):
    list_display = ("original_name", "message", "content_type", "size", "created_at")
    search_fields = ("original_name",)
