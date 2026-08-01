from django.urls import path

from repetitions import views

app_name = "repetitions"

urlpatterns = [
    path("<int:pk>/", views.RehearsalDetailView.as_view(), name="detail"),
    path(
        "<int:pk>/absence/",
        views.ToggleAbsenceView.as_view(),
        name="toggle_absence",
    ),
    path("staff/", views.StaffRehearsalListView.as_view(), name="staff_list"),
    path(
        "staff/nouvelle/",
        views.StaffRehearsalCreateView.as_view(),
        name="staff_create",
    ),
    path(
        "staff/<int:pk>/",
        views.StaffRehearsalEditView.as_view(),
        name="staff_edit",
    ),
    path(
        "staff/<int:pk>/notifier-remplacant/",
        views.StaffNotifySubstituteView.as_view(),
        name="staff_notify_sub",
    ),
]
