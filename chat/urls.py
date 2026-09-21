from django.urls import path

from chat import views

app_name = "chat"

urlpatterns = [
    path("", views.room_list, name="list"),
    path("staff/", views.staff_room, name="staff"),
    path("thematique/nouveau/", views.thematic_create, name="thematic_create"),
    path("prive/nouveau/", views.private_create, name="private_create"),
    path("preferences/", views.account_prefs, name="prefs"),
    path("pj/<int:pk>/", views.attachment_download, name="attachment"),
    path("<int:room_id>/", views.room_detail, name="room"),
    path("<int:room_id>/embed/", views.room_embed_fragment, name="room_embed"),
    path("<int:room_id>/rejoindre/", views.room_rejoin, name="rejoin"),
    path("<int:room_id>/devenir-membre/", views.thematic_join, name="thematic_join"),
    path(
        "<int:room_id>/membres/ajouter/",
        views.thematic_member_add,
        name="thematic_member_add",
    ),
    path(
        "<int:room_id>/membres/retirer/",
        views.thematic_member_remove,
        name="thematic_member_remove",
    ),
    path(
        "<int:room_id>/prive/membres/ajouter/",
        views.private_member_add,
        name="private_member_add",
    ),
    path(
        "<int:room_id>/prive/membres/retirer/",
        views.private_member_remove,
        name="private_member_remove",
    ),
    path("<int:room_id>/api/send/", views.api_send, name="api_send"),
    path("<int:room_id>/api/poll/", views.api_poll, name="api_poll"),
    path("<int:room_id>/api/edit/", views.api_edit, name="api_edit"),
    path("<int:room_id>/api/delete/", views.api_delete, name="api_delete"),
    path("<int:room_id>/api/members/", views.api_members, name="api_members"),
    path("<int:room_id>/api/react/", views.api_react, name="api_react"),
    path("<int:room_id>/api/read/", views.api_read, name="api_read"),
    path("<int:room_id>/api/archive/", views.api_archive, name="api_archive"),
]
