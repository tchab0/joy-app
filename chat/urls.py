from django.urls import path

from chat import views

app_name = "chat"

urlpatterns = [
    path("", views.room_list, name="list"),
    path("preferences/", views.account_prefs, name="prefs"),
    path("pj/<int:pk>/", views.attachment_download, name="attachment"),
    path("<int:room_id>/", views.room_detail, name="room"),
    path("<int:room_id>/rejoindre/", views.room_rejoin, name="rejoin"),
    path("<int:room_id>/api/send/", views.api_send, name="api_send"),
]
