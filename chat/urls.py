from django.urls import path

from chat import views

app_name = "chat"

urlpatterns = [
    path("", views.room_list, name="list"),
    path("staff/", views.staff_room, name="staff"),
    path("preferences/", views.account_prefs, name="prefs"),
    path("pj/<int:pk>/", views.attachment_download, name="attachment"),
    path("<int:room_id>/", views.room_detail, name="room"),
    path("<int:room_id>/rejoindre/", views.room_rejoin, name="rejoin"),
    path("<int:room_id>/api/send/", views.api_send, name="api_send"),
    path("<int:room_id>/api/edit/", views.api_edit, name="api_edit"),
    path("<int:room_id>/api/members/", views.api_members, name="api_members"),
    path("<int:room_id>/api/react/", views.api_react, name="api_react"),
    path("<int:room_id>/api/read/", views.api_read, name="api_read"),
]
