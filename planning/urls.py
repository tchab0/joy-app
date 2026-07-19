from django.urls import path

from planning import views

app_name = "planning"

urlpatterns = [
    # Planning par défaut : calendrier annuel (tous les jours)
    path("", views.PlanningYearCalendarView.as_view(), name="dashboard"),
    path(
        "moi/",
        views.PlanningDashboardView.as_view(),
        name="my_board",
    ),
    # Alias historique
    path(
        "concerts/12-mois/",
        views.PlanningYearCalendarView.as_view(),
        name="upcoming_12_months",
    ),
    path("events/<int:pk>/", views.EventDetailView.as_view(), name="event_detail"),
    path(
        "participations/<int:pk>/respond/",
        views.RespondParticipationView.as_view(),
        name="respond",
    ),
    path(
        "participations/<int:pk>/propose-sub/",
        views.ProposeSubstituteView.as_view(),
        name="propose_sub",
    ),
    path(
        "substitutes/<int:pk>/claim/",
        views.ClaimSubstituteView.as_view(),
        name="claim_sub",
    ),
    path("polls/<int:pk>/", views.PollDetailView.as_view(), name="poll_detail"),
    path(
        "options/<int:pk>/vote/",
        views.VotePollOptionView.as_view(),
        name="vote_option",
    ),
    path(
        "equipment/<int:pk>/status/",
        views.UpdateEquipmentStatusView.as_view(),
        name="equipment_status",
    ),
    path("profile/", views.UpdateProfileSectionView.as_view(), name="update_profile"),
    # Staff
    path("admin/", views.PlanningAdminView.as_view(), name="admin"),
    path(
        "admin/events/create/",
        views.CreateEventView.as_view(),
        name="create_event",
    ),
    path(
        "admin/events/<int:pk>/",
        views.EventRosterView.as_view(),
        name="event_roster",
    ),
    path("admin/polls/create/", views.CreatePollView.as_view(), name="create_poll"),
    path(
        "admin/polls/<int:pk>/lock/",
        views.LockPollView.as_view(),
        name="lock_poll",
    ),
    path(
        "admin/events/<int:pk>/invite/",
        views.InviteMusicianView.as_view(),
        name="invite_musician",
    ),
    path(
        "admin/events/<int:pk>/invite-titulaires/",
        views.InviteTitulairesView.as_view(),
        name="invite_titulaires",
    ),
    path(
        "admin/events/<int:pk>/equipment/",
        views.AddEventEquipmentView.as_view(),
        name="add_event_equipment",
    ),
    path(
        "admin/equipment/create/",
        views.CreateEquipmentItemView.as_view(),
        name="create_equipment",
    ),
    path(
        "admin/musiciens/",
        views.AdminMusiciansView.as_view(),
        name="admin_musicians",
    ),
    path(
        "admin/musiciens/ajouter/",
        views.AdminMusicianEditView.as_view(),
        name="admin_musician_add",
    ),
    path(
        "admin/musiciens/<int:pk>/modifier/",
        views.AdminMusicianEditView.as_view(),
        name="admin_musician_edit",
    ),
    path(
        "admin/musiciens/<int:pk>/retirer/",
        views.AdminMusicianRemoveView.as_view(),
        name="admin_musician_remove",
    ),
]
